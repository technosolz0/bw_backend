import logging
import asyncio
from app.database import AsyncSessionLocal
from app.models.sql_models import Broadcast, BroadcastMessage, Wallet, WalletHistory, Template, Contact, Message
from app.services.whatsapp_meta import send_template_message
from app.services.chat import (
    refund_message_cost, 
    increment_daily_stats, 
    ensure_contact_and_chat, 
    create_template_chat_message
)
from app.services.firebase_service import sync_chat_metadata, sync_message
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
                    
                    # 📊 Persist to Message Table & Sync to Firestore
                    try:
                        # 1. Get Template record for create_template_chat_message
                        if not hasattr(process_broadcast, "_template_cache"):
                            process_broadcast._template_cache = {}
                        
                        t_key = f"{client_id}_{template_name}"
                        if t_key not in process_broadcast._template_cache:
                            # Search by name and clientId
                            t_res = await session.execute(select(Template).where(Template.name == template_name, Template.client_id == client_id))
                            process_broadcast._template_cache[t_key] = t_res.scalars().first()
                        
                        template_record = process_broadcast._template_cache[t_key]
                        
                        if template_record:
                            # 2. Use helper to find/create Contact and Chat
                            effective_chat_id, chat_name, _ = await ensure_contact_and_chat(
                                session, client_id, mobile_no, name=None # Mobile no is used as fallback name
                            )
                            
                            # 3. Create the template-formatted message
                            template_chat_msg = await create_template_chat_message(
                                client_id,
                                template_record,
                                msg, # BroadcastMessage model
                                broadcast, # Broadcast model
                                whatsapp_message_id,
                                "sent",
                                get_ist_time()
                            )
                            
                            if template_chat_msg:
                                # 4. Store in Message table
                                new_chat_msg = Message(
                                    chat_id=effective_chat_id,
                                    client_id=client_id,
                                    **template_chat_msg
                                )
                                session.add(new_chat_msg)
                                
                                # 5. Update Chat last message
                                chat_res = await session.execute(select(Chat).where(Chat.id == effective_chat_id, Chat.client_id == client_id))
                                chat = chat_res.scalars().first()
                                if chat:
                                    chat.last_message = template_chat_msg.get("content", "")
                                    chat.last_message_time = get_ist_time()
                                
                                await session.commit() # Commit each to ensure Firestore syncs valid data
                                
                                # 6. Firestore Sync
                                await sync_chat_metadata(effective_chat_id, client_id, {
                                    "lastMessage": template_chat_msg.get("content", ""),
                                    "lastMessageTime": get_ist_time(),
                                    "phoneNumber": mobile_no,
                                    "name": chat_name
                                })
                                
                                await sync_message(effective_chat_id, client_id, whatsapp_message_id, {
                                    "content": template_chat_msg.get("content", ""),
                                    "timestamp": get_ist_time(),
                                    "isFromMe": True,
                                    "senderName": broadcast.admin_name,
                                    "status": "sent",
                                    "whatsappMessageId": whatsapp_message_id,
                                    "messageType": template_chat_msg.get("message_type", "text"),
                                    "mediaUrl": template_chat_msg.get("media_url"),
                                    "fileName": template_chat_msg.get("file_name")
                                })
                                logger.info(f"✅ Broadcast message {whatsapp_message_id} persisted and synced for {mobile_no}")
                        else:
                            logger.warning(f"Template {template_name} not found in DB, skipping persistence for {mobile_no}")
                            await session.commit()

                    except Exception as persistence_err:
                        logger.error(f"Failed to persist broadcast message: {persistence_err}")
                        await session.rollback()

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
