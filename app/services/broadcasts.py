import logging
import asyncio
from app.database import AsyncSessionLocal
from app.models.sql_models import Broadcast, BroadcastMessage, Wallet, WalletHistory, Template, Contact
from app.services.whatsapp_meta import send_template_message
from app.services.chat import refund_message_cost, increment_daily_stats
from app.services.utils import get_secrets
from sqlalchemy.future import select
from sqlalchemy import update, func
import datetime
import uuid
import os
from datetime import timezone, timedelta

logger = logging.getLogger(__name__)

def get_ist_time():
    return datetime.datetime.now(timezone(timedelta(hours=5, minutes=30)))

async def start_broadcast(client_id: str, broadcast_id: str):
    """
    Initializes a broadcast. This would be called by the router after creating the Broadcast record.
    In this implementation, we assume the Broadcast record and its associated BroadcastMessage records 
    already exist in the database (created when the user uploads the CSV/Contacts).
    """
    logger.info(f"🚀 Starting broadcast {broadcast_id} for client {client_id}")
    
    # Run in background
    asyncio.create_task(process_broadcast(client_id, broadcast_id))
    return {"success": True, "message": "Broadcast started in background"}

async def process_broadcast(client_id: str, broadcast_id: str):
    async with AsyncSessionLocal() as session:
        try:
            # 1. Fetch Broadcast and Template
            result = await session.execute(
                select(Broadcast).where(Broadcast.id == broadcast_id, Broadcast.client_id == client_id)
            )
            broadcast = result.scalars().first()
            if not broadcast:
                logger.error(f"Broadcast {broadcast_id} not found")
                return

            broadcast.status = "Sending"
            await session.commit()

            secrets = await get_secrets(client_id)
            
            # 2. Fetch all messages for this broadcast
            msg_result = await session.execute(
                select(BroadcastMessage).where(BroadcastMessage.broadcast_id == broadcast_id)
            )
            messages = msg_result.scalars().all()
            
            logger.info(f"Processing {len(messages)} messages for broadcast {broadcast_id}")

            # 3. Process messages
            for msg in messages:
                try:
                    payload = msg.payload or {}
                    
                    template_name = payload.get("template")
                    language = payload.get("language")
                    mobile_no = payload.get("mobileNo")
                    body_vars = payload.get("bodyVariables", [])
                    header_vars = payload.get("headerVariables", {})
                    button_vars = payload.get("buttonVariables", [])
                    
                    media_id = None
                    media_type = "image"
                    header_text = None
                    
                    if header_vars:
                        h_type = header_vars.get("type")
                        if h_type == "text":
                            header_text = header_vars.get("data", {}).get("text")
                        else:
                            media_id = header_vars.get("data", {}).get("mediaId")
                            media_type = h_type or "image"
                    
                    button_payloads = [b.get("payload") for b in button_vars] if button_vars else None

                    # Send message
                    response = await send_template_message(
                        client_id, 
                        secrets, 
                        template_name, 
                        language, 
                        body_vars, 
                        media_id, 
                        mobile_no, 
                        header_text, 
                        media_type,
                        button_payloads
                    )
                    
                    # Update message status
                    whatsapp_message_id = response.get("messages", [{}])[0].get("id")
                    
                    msg.status = "sent"
                    msg.whatsapp_message_id = whatsapp_message_id
                    msg.sent_at = get_ist_time()
                    
                    # Update stats
                    today = get_ist_time().strftime("%Y-%m-%d")
                    await increment_daily_stats(client_id, today, 'sent')
                    
                except Exception as e:
                    logger.error(f"Failed to send message {msg.id}: {e}")
                    msg.status = "failed"
                    msg.error_code = str(e)
                    msg.failed_at = get_ist_time()
                    
                    await refund_message_cost(client_id, broadcast_id, msg.cost)
                
                await session.commit()
                await asyncio.sleep(0.1)

            # 4. Finalize broadcast
            broadcast.status = "Sent"
            broadcast.updated_at = get_ist_time()
            await session.commit()
            logger.info(f"✅ Broadcast {broadcast_id} completed")

        except Exception as e:
            logger.error(f"Critical error in process_broadcast: {e}")
            if broadcast:
                broadcast.status = "Failed"
                await session.commit()

async def create_broadcast_record(client_id: str, data: dict):
    """
    Creates Broadcast and BroadcastMessage hooks.
    Data format: {templateId, adminName, attachmentId, audienceType, contacts: [{mobileNo, bodyVariables, ...}], totalCost}
    """
    async with AsyncSessionLocal() as session:
        broadcast_id = str(uuid.uuid4())
        
        new_broadcast = Broadcast(
            id=broadcast_id,
            client_id=client_id,
            template_id=data.get("templateId"),
            admin_name=data.get("adminName"),
            attachment_id=data.get("attachmentId"),
            audience_type=data.get("audienceType"),
            status="Draft",
            sent=0,
            delivered=0,
            read=0,
            failed=0,
            created_at=get_ist_time()
        )
        session.add(new_broadcast)
        
        # Add messages
        contacts = data.get("contacts", [])
        for c in contacts:
            msg_id = str(uuid.uuid4())
            # Construct payload for BroadcastMessage
            payload = {
                "template": data.get("templateName"),
                "language": data.get("language"),
                "type": data.get("type"),
                "bodyVariables": c.get("bodyVariables"),
                "headerVariables": data.get("headerVariables"),
                "mobileNo": c.get("mobileNo"),
                "buttonVariables": data.get("buttonVariables")
            }
            
            b_msg = BroadcastMessage(
                id=msg_id,
                broadcast_id=broadcast_id,
                client_id=client_id,
                payload=payload,
                status="pending",
                cost=data.get("messageCost", 0.0)
            )
            session.add(b_msg)
            
        # Deduct wallet
        total_cost = data.get("totalCost", 0.0)
        await session.execute(
            update(Wallet).where(Wallet.client_id == client_id).values(balance=Wallet.balance - total_cost)
        )
        
        # History
        history = WalletHistory(
            id=str(uuid.uuid4()),
            client_id=client_id,
            broadcast_id=broadcast_id,
            chargeable_messages=len(contacts),
            chargeable_amount=total_cost
        )
        session.add(history)
        
        await session.commit()
        return broadcast_id
