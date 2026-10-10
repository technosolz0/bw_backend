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
                    
                    # 1. Pre-fetch Template record for header requirements & later persistence
                    if not hasattr(process_broadcast, "_template_cache"):
                        process_broadcast._template_cache = {}
                    
                    t_key = f"{client_id}_{template_name}"
                    if t_key not in process_broadcast._template_cache:
                        # Search by name and clientId
                        t_res = await session.execute(select(Template).where(Template.name == template_name, Template.client_id == client_id))
                        process_broadcast._template_cache[t_key] = t_res.scalars().first()
                    
                    template_record = process_broadcast._template_cache[t_key]

                    media_id = None
                    media_type = "image"
                    header_text = None
                    
                    if header_vars:
                        h_type = str(header_vars.get("type") or "").strip().lower()
                        h_data = header_vars.get("data")
                        if isinstance(h_data, dict):
                            if h_type == "text":
                                header_text = h_data.get("text")
                            else:
                                media_id = h_data.get("mediaId") or h_data.get("media_id") or h_data.get("link") or h_data.get("url")
                                if h_type:
                                    media_type = h_type
                        elif isinstance(h_data, str):
                            if h_type == "text":
                                header_text = h_data
                            else:
                                media_id = h_data
                                if h_type:
                                    media_type = h_type
                        else:
                            if h_type == "text":
                                header_text = header_vars.get("text")
                            else:
                                media_id = header_vars.get("mediaId") or header_vars.get("media_id") or header_vars.get("link") or header_vars.get("url")
                                if h_type:
                                    media_type = h_type
                    
                    # Fallback to broadcast level media_id or payload mediaId
                    if not media_id and broadcast.media_id:
                        media_id = broadcast.media_id
                    if not media_id and payload.get("mediaId"):
                        media_id = payload.get("mediaId")
                    
                    # If template has header format, align media_type and fallback to example handle if missing
                    if template_record and template_record.components:
                        for comp in template_record.components:
                            if comp.get("type") == "HEADER":
                                h_fmt = str(comp.get("format") or "").upper()
                                if h_fmt in ["IMAGE", "VIDEO", "DOCUMENT"]:
                                    media_type = h_fmt.lower()
                                    if not media_id:
                                        ex_handles = comp.get("example", {}).get("header_handle", [])
                                        if ex_handles and isinstance(ex_handles, list) and ex_handles[0]:
                                            media_id = ex_handles[0]
                                            logger.info(f"Using template example header_handle for {mobile_no}: {media_id}")
                                elif h_fmt == "TEXT" and not header_text:
                                    ex_texts = comp.get("example", {}).get("header_text", [])
                                    if ex_texts and isinstance(ex_texts, list) and ex_texts[0]:
                                        header_text = ex_texts[0]
                    
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
                    broadcast.sent = (broadcast.sent or 0) + 1
                    
                    # 📊 Persist to Message Table & Sync to Firestore
                    try:
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
                    broadcast.failed = (broadcast.failed or 0) + 1
                    code = 500
                    if hasattr(e, "response") and getattr(e.response, "text", None):
                        try:
                            err_json = e.response.json()
                            if isinstance(err_json, dict) and "error" in err_json:
                                meta_code = err_json["error"].get("code")
                                if isinstance(meta_code, int):
                                    code = meta_code
                        except Exception:
                            pass
                    if code == 500 and hasattr(e, "response") and getattr(e.response, "status_code", None):
                        try:
                            code = int(e.response.status_code)
                        except Exception:
                            code = 500
                    elif code == 500 and "400" in str(e):
                        code = 400
                    elif code == 500 and "401" in str(e):
                        code = 401
                    elif code == 500 and "403" in str(e):
                        code = 403
                    elif code == 500 and "404" in str(e):
                        code = 404
                    msg.error_code = code
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

def parse_iso_datetime(dt_str):
    if not dt_str:
        return None
    try:
        cleaned = dt_str.replace('Z', '+00:00')
        return datetime.datetime.fromisoformat(cleaned)
    except Exception:
        try:
            return datetime.datetime.strptime(dt_str.split('.')[0], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None

async def create_broadcast_record(client_id: str, data: dict):
    """
    Creates Broadcast and BroadcastMessage hooks.
    """
    async with AsyncSessionLocal() as session:
        broadcast_id = data.get("id") or str(uuid.uuid4())
        
        # Overwrite protection: delete existing records with this broadcast_id if present
        if data.get("id"):
            # Check if it exists
            exists_res = await session.execute(select(Broadcast).where(Broadcast.id == broadcast_id))
            if exists_res.scalars().first():
                await session.execute(delete(BroadcastMessage).where(BroadcastMessage.broadcast_id == broadcast_id))
                await session.execute(delete(WalletHistory).where(WalletHistory.broadcast_id == broadcast_id))
                await session.execute(delete(Broadcast).where(Broadcast.id == broadcast_id))
        
        delivery_timestamp_dt = parse_iso_datetime(data.get("deliveryTimestamp"))
        status = data.get("status") or "Draft"
        
        new_broadcast = Broadcast(
            id=broadcast_id,
            client_id=client_id,
            broadcast_name=data.get("broadcastName"),
            description=data.get("description"),
            template_id=data.get("templateId"),
            admin_name=data.get("adminName"),
            admin_id=data.get("adminId"),
            attachment_id=data.get("attachmentId"),
            audience_type=data.get("audienceType"),
            status=status,
            sent=0,
            delivered=0,
            read=0,
            failed=0,
            created_at=get_ist_time(),
            template_variables=data.get("templateVariables"),
            media_id=data.get("mediaId"),
            delivery_type=data.get("deliveryType"),
            delivery_timestamp=delivery_timestamp_dt,
            total_cost=data.get("totalCost", 0.0),
            clicks=0,
            replied=0,
            enable_retry=data.get("enableRetry", False),
            retry_campaign_status=data.get("retryCampaignStatus"),
            card_variables=data.get("cardVariables"),
            card_attachment_ids=data.get("cardAttachmentIds"),
            contact_ids=data.get("contactIds")
        )
        session.add(new_broadcast)
        
        # Resolve template_name and language if missing
        template_name = data.get("templateName")
        language = data.get("language")
        if not template_name or not language:
            template_id = data.get("templateId")
            if template_id:
                t_res = await session.execute(
                    select(Template).where(
                        (Template.id == template_id) | (Template.name == template_id),
                        Template.client_id == client_id
                    )
                )
                t_rec = t_res.scalars().first()
                if t_rec:
                    template_name = template_name or t_rec.name
                    language = language or t_rec.language
            
            if not template_name or not language:
                try:
                    from app.services.whatsapp_meta import get_meta_templates
                    meta_res = await get_meta_templates(client_id, status="APPROVED", fields="id,name,language")
                    if isinstance(meta_res, dict) and "data" in meta_res:
                        for tmpl in meta_res.get("data", []):
                            if str(tmpl.get("id")) == str(data.get("templateId")) or tmpl.get("name") == str(data.get("templateId")):
                                template_name = template_name or tmpl.get("name")
                                language = language or tmpl.get("language")
                                break
                except Exception as fallback_err:
                    logger.warning(f"Meta fallback template lookup failed: {fallback_err}")

        # Add messages
        contacts = data.get("contacts", []) or []
        default_header_vars = data.get("headerVariables")
        if not default_header_vars and data.get("mediaId"):
            default_header_vars = {
                "type": "image",
                "data": {
                    "mediaId": data.get("mediaId")
                }
            }

        for c in contacts:
            msg_id = str(uuid.uuid4())
            # Construct payload for BroadcastMessage
            payload = {
                "template": template_name,
                "language": language or "en_US",
                "type": data.get("type"),
                "bodyVariables": c.get("bodyVariables"),
                "headerVariables": c.get("headerVariables") or default_header_vars,
                "mobileNo": c.get("mobileNo"),
                "buttonVariables": c.get("buttonVariables") or data.get("buttonVariables")
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
            
        # Deduct wallet only if status is not Draft
        if status.lower() != "draft":
            total_cost = data.get("totalCost", 0.0)
            # Check if wallet exists for this client first
            w_res = await session.execute(select(Wallet).where(Wallet.client_id == client_id))
            wallet = w_res.scalars().first()
            if not wallet:
                wallet = Wallet(client_id=client_id, balance=0.0)
                session.add(wallet)
            
            wallet.balance = wallet.balance - total_cost
            
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
