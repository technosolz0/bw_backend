import logging
from app.database import AsyncSessionLocal
from app.models.sql_models import WebhookLog, Template, Contact, Chat, Message, Broadcast, BroadcastMessage, Wallet, WalletHistory
from app.services.utils import get_secrets, extract_phone_number
from app.services.chat import (
    increment_daily_stats, 
    send_whatsapp_message_helper, 
    download_and_upload_media, 
    mark_message_as_read,
    refund_message_cost
)
from app.services.gemini import generate_content_with_file_search
from sqlalchemy.future import select
from sqlalchemy import update, or_, and_
import datetime
import os
import re
import urllib.parse
import time
import requests
import json

logger = logging.getLogger(__name__)

async def log_webhook(client_id, type_str, payload, status="SUCCESS"):
    async with AsyncSessionLocal() as session:
        try:
            # Check if payload is dict, if so remove any nested nonsense if needed
            # For JSON column, we just pass the dict.
            log = WebhookLog(
                client_id=client_id,
                type=type_str,
                payload=payload,
                status=status,
                created_at=datetime.datetime.now()
            )
            session.add(log)
            await session.commit()
        except Exception as e:
            logger.error(f"LOGGING ERROR: {e}")
            await session.rollback()

async def handle_status_update(client_id, value):
    msg_template_id = str(value.get("message_template_id", ""))
    if not msg_template_id:
        return

    reason_block = None
    if value.get("disable_info"):
        reason_block = {
            "type": "disable",
            "info": value["disable_info"]
        }
    if value.get("other_info"):
        reason_block = {
            "type": "other_info",
            "info": value["other_info"]
        }
    if value.get("rejection_info"):
        reason_block = {
            "type": "rejection_info",
            "info": value["rejection_info"]
        }

    status = value.get("event", "")
    category = value.get("message_template_category", "")

    async with AsyncSessionLocal() as session:
        try:
             result = await session.execute(select(Template).where(Template.id == msg_template_id, Template.client_id == client_id))
             template = result.scalars().first()
             if template:
                 template.status = status
                 template.category = category
                 if reason_block:
                     template.reason = reason_block
                 template.updated_at = datetime.datetime.now()
             else:
                 # If template doesn't exist, we might create it but usually it should exist.
                 pass
             await session.commit()
        except Exception as e:
             logger.error(f"Template Status Update Error: {e}")

async def handle_category_update(client_id, value):
    msg_template_id = str(value.get("message_template_id", ""))
    if not msg_template_id:
        return

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(Template).where(Template.id == msg_template_id, Template.client_id == client_id))
            template = result.scalars().first()
            if template:
                template.category = value.get("new_category") or value.get("correct_category") or ""
                template.updated_at = datetime.datetime.now()
                await session.commit()
        except Exception as e:
             logger.error(f"Template Category Update Error: {e}")

async def handle_chat_message(client_id, value):
    try:
        messages = value.get("messages", [])
        if not messages:
            logger.info("No messages in webhook value")
            return

        secrets = await get_secrets(client_id)
        if not secrets:
            logger.error(f"Secrets not found for {client_id}")
            return

        for message in messages:
            from_phone = message.get("from")
            message_id = message.get("id")
            timestamp = message.get("timestamp")
            message_type = message.get("type")

            phone_data = extract_phone_number(from_phone)
            phone_number = phone_data["phoneNumber"]
            country_code = phone_data["countryCode"]

            logger.info(f"Extracted - Phone: {phone_number}, Country Code: {country_code}")

            message_text = ""
            context = None
            media_url = None
            file_name = None
            mime_type = None
            caption = None
            
            # ... Message extraction logic same as before ...
            if message_type == "text":
                message_text = message.get("text", {}).get("body", "")
                context = message.get("text", {}).get("context")

            elif message_type == "image":
                caption = message.get("image", {}).get("caption", "")
                message_text = caption or "📷 Image"
                mime_type = message.get("image", {}).get("mime_type", "image/jpeg")
                media_id = message.get("image", {}).get("id")
                if media_id:
                    uploaded = await download_and_upload_media(client_id, secrets, media_id, mime_type, None, message_id)
                    if uploaded:
                        media_url = uploaded["url"]
                        file_name = uploaded["filename"]
                    else:
                        message_text = "[Failed to save image]"
                context = message.get("image", {}).get("context")

            elif message_type == "document":
                doc = message.get("document", {})
                caption = doc.get("caption", "")
                file_name = doc.get("filename", "document")
                mime_type = doc.get("mime_type", "application/octet-stream")
                message_text = caption or f"📄 {file_name}"
                media_id = doc.get("id")
                if media_id:
                    uploaded = await download_and_upload_media(client_id, secrets, media_id, mime_type, file_name, message_id)
                    if uploaded:
                        media_url = uploaded["url"]
                        file_name = uploaded["filename"]
                    else:
                        message_text = f"[Failed to save document: {file_name}]"
                context = doc.get("context")

            elif message_type == "video":
                caption = message.get("video", {}).get("caption", "")
                message_text = caption or "🎥 Video"
                mime_type = message.get("video", {}).get("mime_type", "video/mp4")
                media_id = message.get("video", {}).get("id")
                if media_id:
                    uploaded = await download_and_upload_media(client_id, secrets, media_id, mime_type, None, message_id)
                    if uploaded:
                        media_url = uploaded["url"]
                        file_name = uploaded["filename"]
                    else:
                        message_text = "[Failed to save video]"
                context = message.get("video", {}).get("context")
            
            elif message_type == "audio" or message_type == "voice":
                 is_voice = message.get("audio", {}).get("voice", False)
                 message_text = "🎤 Voice Message" if is_voice else "🎵 Audio"
                 mime_type = message.get("audio", {}).get("mime_type", "audio/ogg")
                 media_id = message.get("audio", {}).get("id")
                 if media_id:
                     voice_filename = f"voice_{message_id}.ogg" if is_voice else None
                     uploaded = await download_and_upload_media(client_id, secrets, media_id, mime_type, voice_filename, message_id)
                     if uploaded:
                        media_url = uploaded["url"]
                        file_name = uploaded["filename"]
                     else:
                        message_text = "[Failed to save audio]"
                 context = message.get("audio", {}).get("context") or message.get("voice", {}).get("context") 
            
            elif message_type == "button":
                message_text = message.get("button", {}).get("text", "Button")
                context = message.get("button", {}).get("context")
            
            else:
                logger.info(f"Unsupported message type: {message_type}")
                continue

            logger.info(f"Message from {phone_number}: {message_text} ({message_type})")

            # Contact & Chat Logic with DB Session
            async with AsyncSessionLocal() as session:
                # Find or Create Contact
                result = await session.execute(
                    select(Contact).where(
                        Contact.client_id == client_id,
                        Contact.phone_number == phone_number
                    )
                )
                contact = result.scalars().first()
                contact_id = None
                contact_name = "Unknown User"
                
                if contact:
                    contact_id = contact.id
                    contact_name = f"{contact.f_name or ''} {contact.l_name or ''}".strip()
                    if not contact_name: contact_name = phone_number
                    contact.last_contacted = datetime.datetime.now()
                else:
                    # Create new contact
                    profile_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "")
                    f_name, l_name = "", ""
                    if profile_name:
                        parts = profile_name.split(" ")
                        f_name = parts[0]
                        l_name = " ".join(parts[1:])
                    
                    contact_id = phone_number # Or UUID. Using phone for simplicity/compatibility
                    new_contact = Contact(
                        id=contact_id,
                        client_id=client_id,
                        phone_number=phone_number,
                        country_code=country_code,
                        f_name=f_name,
                        l_name=l_name,
                        notes="Auto-created from WhatsApp message",
                        tags=[],
                        last_contacted=datetime.datetime.now(),
                        created_at=datetime.datetime.now()
                    )
                    session.add(new_contact)
                    await session.flush() # Ensure ID is available if generated, but we set it manually
                    contact_name = f"{f_name} {l_name}".strip() if (f_name or l_name) else phone_number
                
                # Find or Create Chat
                chat_result = await session.execute(
                    select(Chat).where(Chat.id == contact_id, Chat.client_id == client_id)
                )
                chat = chat_result.scalars().first()
                
                full_phone_number = f"{country_code}{phone_number}"
                has_ai_response = False
                ai_response_enabled = False
                
                if not chat:
                    chat = Chat(
                        id=contact_id,
                        client_id=client_id,
                        contact_id=contact_id,
                        name=contact_name,
                        phone_number=full_phone_number,
                        last_message=message_text,
                        last_message_time=datetime.datetime.now(),
                        is_online=False,
                        ai_response_enabled=False,
                        is_active=False,
                        un_read=False,
                        created_at=datetime.datetime.now()
                    )
                    session.add(chat)
                else:
                    chat.last_message = message_text
                    chat.last_message_time = datetime.datetime.now()
                    chat.user_last_message_time = datetime.datetime.now()
                    if not chat.is_active:
                        chat.un_read = True
                    ai_response_enabled = chat.ai_response_enabled

                await session.commit()
                
                # AI Response Logic
                if ai_response_enabled:
                    await mark_message_as_read(secrets, message_id, True)
                    if message_type == 'text':
                        try:
                            ai_response = await generate_content_with_file_search(
                                client_id, 
                                message_text, 
                                secrets.get("googleApiKey"), 
                                [secrets.get("storeId"), secrets.get("qnaStoreId")], 
                                contact_id
                            )
                            await send_whatsapp_message_helper({
                                "clientId": client_id,
                                "phoneNumber": phone_number,
                                "message": ai_response,
                                "chatId": contact_id,
                                "messageType": "text"
                            })
                            has_ai_response = True
                        except Exception as e:
                             logger.error(f"AI Response Error: {e}")
                    else:
                        await send_whatsapp_message_helper({
                            "clientId": client_id,
                            "phoneNumber": phone_number,
                            "message": "Sorry, could not understand your request. Try again later.",
                            "chatId": contact_id,
                            "messageType": "text"
                        })
                        has_ai_response = True
                
                # Broadcast Helper
                # Re-open session or use separate session inside helper? 
                # Ideally helper should accept session but structure is messy.
                # I'll update broadcast_message_helper to handle its own session OR refactor it.
                # For now let's call it.
                template_chat_msg, broadcast_msg_to_update = await broadcast_message_helper(client_id, 'Sending', contact_id, full_phone_number)
                
                if not template_chat_msg:
                     template_chat_msg, broadcast_msg_to_update = await broadcast_message_helper(client_id, 'Sent', contact_id, full_phone_number)
                
                if template_chat_msg:
                    # Save template message to chat
                    async with AsyncSessionLocal() as session:
                        tmpl_msg = Message(
                             chat_id=contact_id,
                             client_id=client_id,
                             **template_chat_msg
                        )
                        session.add(tmpl_msg)
                        if broadcast_msg_to_update:
                             # broadcast_msg_to_update is likely a DB object or ID
                             # Since I need to rewrite broadcast_message_helper, I'll assume it returns ID or object
                             if isinstance(broadcast_msg_to_update, str):
                                 await session.execute(update(BroadcastMessage).where(BroadcastMessage.id == broadcast_msg_to_update).values(added_to_chat=True))
                        await session.commit()

                # Save Incoming Message
                ts_millis = int(timestamp) * 1000
                ts_dt = datetime.datetime.fromtimestamp(ts_millis / 1000.0)
                
                async with AsyncSessionLocal() as session:
                    new_msg = Message(
                        chat_id=contact_id,
                        client_id=client_id,
                        content=message_text,
                        timestamp=ts_dt,
                        is_from_me=False,
                        sender_name=contact_name,
                        status="read" if has_ai_response else "delivered",
                        whatsapp_message_id=message_id,
                        message_type=message_type,
                        media_url=media_url,
                        file_name=file_name,
                        mime_type=mime_type,
                        caption=caption,
                        context=context
                    )
                    session.add(new_msg)
                    await session.commit()
                
                logger.info(f"Message stored successfully for contact {contact_id}")

    except Exception as e:
        logger.error(f"Error handling chat message: {e}")
        # In Python we don't necessarily rethrow if inside an event loop unless strict
        raise e

async def broadcast_message_helper(client_id, status, contact_id, full_phone_number):
    # This helper now takes client_id and status/contact details
    # We query Broadcasts and BroadcastMessages via SQL
    
    template_chat_message = None
    message_doc_id = None # Return ID string
    
    async with AsyncSessionLocal() as session:
        try:
            # Find candidate broadcasts
            # We want Broadcasts where status match (passed in arg is likely 'Sending' or 'Sent') (Wait, arg status is used to filter?)
            # The original code filtered Broadcasts by status.
            
            # Since JSON contain query in standard SQLA is dialect specific, we'll fetch active broadcasts with status and filter in python for now
            # Optimization: Filter by client_id and status
            
            # Using specific query if possible:
            # from sqlalchemy import cast
            # from sqlalchemy.dialects.postgresql import JSONB
            
            query = select(Broadcast).where(
                Broadcast.client_id == client_id,
                Broadcast.status == status
            ).order_by(Broadcast.created_at.desc()).limit(20) # Limit to recent 20 to avoid scanning all
            
            result = await session.execute(query)
            broadcasts = result.scalars().all()
            
            target_broadcast = None
            
            for b in broadcasts:
                c_ids = b.contact_ids or []
                if b.audience_type == 1:
                    if full_phone_number in c_ids:
                        target_broadcast = b
                        break
                else:
                    if contact_id in c_ids:
                        target_broadcast = b
                        break
            
            if target_broadcast:
                # Find the specific message in this broadcast
                # Original logic: payload.mobileNo == fullPhoneNumber AND status in [delivered, read] AND addedToChat == False
                
                # Check BroadcastMessage table
                # We need to dig into payload JSON to find mobileNo? 
                # Or maybe we can rely on something else.
                # The payload is stored in BroadcastMessage.payload
                
                # We'll fetch messages for this broadcast that are delivered/read and not added
                msg_query = select(BroadcastMessage).where(
                    BroadcastMessage.broadcast_id == target_broadcast.id,
                    BroadcastMessage.status.in_(["delivered", "read"]),
                    BroadcastMessage.added_to_chat == False
                )
                
                msg_result = await session.execute(msg_query)
                msgs = msg_result.scalars().all()
                
                target_msg = None
                for m in msgs:
                    # Check payload mobileNo
                    p_mobile = m.payload.get("mobileNo")
                    if p_mobile == full_phone_number:
                        target_msg = m
                        break
                
                if target_msg:
                    message_doc_id = target_msg.id
                    
                    # Get Template Data
                    t_result = await session.execute(select(Template).where(
                        Template.id == target_broadcast.template_id, 
                        Template.client_id == client_id
                    ))
                    template = t_result.scalars().first()
                    
                    if template:
                        # Create template chat message dict
                        template_chat_message = await create_template_chat_message(
                            client_id,
                            template,
                            target_msg,
                            target_broadcast,
                            target_msg.whatsapp_message_id,
                            target_msg.status,
                            target_msg.delivered_at if target_msg.status == 'delivered' else target_msg.read_at
                        )

        except Exception as e:
            logger.error(f"Broadcast Message Helper Error: {e}")
            
    return template_chat_message, message_doc_id

async def create_template_chat_message(client_id, template, message, broadcast, whatsapp_message_id, status, status_timestamp):
    # template is now SQL model, message is BroadcastMessage model, broadcast is Broadcast model
    
    payload = message.payload or {}
    payload_type = payload.get("type", "").upper()
    template_message = None
    
    def replace_body_params(text, variables):
        for i, var in enumerate(variables):
            text = text.replace(f"{{{{{i+1}}}}}", str(var))
        return text

    components = template.components or []
    
    header_comp = next((c for c in components if c['type'] == 'HEADER'), {})
    body_comp = next((c for c in components if c['type'] == 'BODY'), {})
    footer_comp = next((c for c in components if c['type'] == 'FOOTER'), {})
    buttons_comp = next((c for c in components if c['type'] == 'BUTTONS'), {})

    body_text = body_comp.get("text", "")
    body_vars = payload.get("bodyVariables", [])
    content = replace_body_params(body_text, body_vars)
    
    sender_name = broadcast.admin_name
    
    base_msg = {
        "is_from_me": True,  # DB uses snake_case keys for dict unpacking? No, this dict is used to create Message model later
        # Wait, the caller uses **template_chat_message to create Message(..). 
        # So keys must match Message model attributes (snake_case).
        "is_from_me": True,
        # "isTemplateMessage": True, # Model doesn't have this field? 'message_type' handles it maybe?
        "sender_name": sender_name,
        "status": status,
        # "statusTimestamp": status_timestamp, # Not a field in Message model, usage specific?
        # Message model has sent_at, delivered_at, read_at.
        "whatsapp_message_id": whatsapp_message_id,
        "sender_avatar": None,
        "caption": None,
        #"footer": footer_comp.get("text"), # Not in Message Model? maybe append to content?
        "media_url": None,
        "file_name": None,
        "message_type": "text"
    }
    
    # If footer exists, maybe append to content?
    footer_text = footer_comp.get("text")
    if footer_text:
        content += f"\n\n{footer_text}"
    
    if status == 'delivered':
        base_msg['delivered_at'] = status_timestamp
    elif status == 'read':
        base_msg['read_at'] = status_timestamp
    else:
        base_msg['sent_at'] = status_timestamp # Default

    if payload_type == 'TEXT':
        header_text = header_comp.get("text")
        if header_text:
             content = f"*{header_text}*\n{content}"
             
        base_msg.update({
             "content": content,
        })
        template_message = base_msg
        
    elif payload_type == 'MEDIA':
        header_vars = payload.get("headerVariables", {})
        file_name = header_vars.get("data", {}).get("fileName")
        attachment_id = broadcast.attachment_id
        
        # Local File Storage URL
        dir_rel_path = f"broadcasts_media/{client_id}/{attachment_id}"
        server_url = os.getenv("SERVER_URL", "http://localhost:8000")
        media_url = f"{server_url}/static/{dir_rel_path}/{file_name}"

        base_msg.update({
            "content": content,
            "file_name": file_name,
            "media_url": media_url,
            "message_type": header_vars.get("type", "").lower()
        })
        template_message = base_msg
        
    elif payload_type == 'INTERACTIVE':
        # simplifying interactive checks
        header_vars = payload.get("headerVariables", {})
        media_url = None
        file_name = None
        
        if header_vars:
             if header_vars.get("type") != 'text':
                file_name = header_vars.get("data", {}).get("fileName")
                attachment_id = broadcast.attachment_id
                dir_rel_path = f"broadcasts_media/{client_id}/{attachment_id}"
                server_url = os.getenv("SERVER_URL", "http://localhost:8000")
                media_url = f"{server_url}/static/{dir_rel_path}/{file_name}"

        # Buttons - not stored in Message model explicitly aside from context?
        # appending buttons to content for visibility
        if buttons_comp:
            buttons_text = "\n".join([f"[{b.get('text')}]" for b in buttons_comp.get("buttons", [])])
            content += f"\n\n{buttons_text}"

        base_msg.update({
            "content": content,
            "file_name": file_name,
            "media_url": media_url,
            "message_type": 'interactive',
        })
        template_message = base_msg

    return template_message

async def handle_message_status_update(client_id, value):
    statuses = value.get("statuses", [])
    if not statuses:
        return
        
    logger.info(f"📊 Processing {len(statuses)} status update(s)")
    
    async with AsyncSessionLocal() as session:
        for status_obj in statuses:
            whatsapp_message_id = status_obj.get("id")
            status = status_obj.get("status")
            timestamp = status_obj.get("timestamp")
            billable = status_obj.get("pricing", {}).get("billable")
            
            if not whatsapp_message_id: continue
            
            logger.info(f"🔄 Updating status for: {whatsapp_message_id} → {status}")
            
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            status_timestamp = datetime.datetime.fromtimestamp(int(timestamp))

            # 1. Check BroadcastMessage
            result = await session.execute(select(BroadcastMessage).where(BroadcastMessage.whatsapp_message_id == whatsapp_message_id))
            b_msg = result.scalars().first()
            
            if b_msg:
                # Update BroadcastMessage
                if b_msg.status == status: continue
                
                b_msg.status = status
                
                # Fetch Broadcast to update stats
                b_result = await session.execute(select(Broadcast).where(Broadcast.id == b_msg.broadcast_id))
                broadcast = b_result.scalars().first()
                if not broadcast: continue

                if status == 'failed':
                    b_msg.error_code = status_obj.get("errors", [{}])[0].get("code")
                    b_msg.failed_at = status_timestamp
                    broadcast.failed += 1
                    # Refund
                    await refund_message_cost(client_id, broadcast.id, b_msg.cost)
                    await increment_daily_stats(client_id, today, 'failed')
                    
                elif status == 'sent':
                    b_msg.sent_at = status_timestamp
                    broadcast.sent += 1
                    if not billable:
                        await refund_message_cost(client_id, broadcast.id, b_msg.cost)
                    await increment_daily_stats(client_id, today, 'sent')
                    
                elif status == 'delivered':
                    b_msg.delivered_at = status_timestamp
                    broadcast.delivered += 1
                    await increment_daily_stats(client_id, today, 'delivered')
                    
                elif status == 'read':
                    b_msg.read_at = status_timestamp
                    broadcast.read += 1
                    await increment_daily_stats(client_id, today, 'read')
                
                await session.commit()
                continue # broadcast handled

            # 2. Check Chat Message
            # Only need to join Client? Or just query Message directly (unique ID usually)
            m_result = await session.execute(select(Message).where(Message.whatsapp_message_id == whatsapp_message_id))
            message = m_result.scalars().first()
            
            if message:
                current_status = message.status or "sent"
                status_priority = {"sent": 1, "delivered": 2, "read": 3, "failed": 1}
                 
                new_prio = status_priority.get(status, 1)
                curr_prio = status_priority.get(current_status, 1)
                 
                if new_prio >= curr_prio:
                    message.status = status
                    if status == 'failed':
                        message.error_code = status_obj.get("errors", [{}])[0].get("code")
                        message.error_description = status_obj.get("errors", [{}])[0].get("error_data", {}).get("details")
                        message.failed_at = status_timestamp
                    elif status == 'delivered':
                        message.delivered_at = status_timestamp
                        await increment_daily_stats(client_id, today, 'delivered')
                    elif status == 'read':
                        message.read_at = status_timestamp
                        await increment_daily_stats(client_id, today, 'read')
                    
                    await session.commit()
                else:
                    logger.info(f"Skipping status update {status} for {whatsapp_message_id} (current: {current_status})")
            else:
                logger.info(f"Message ID {whatsapp_message_id} not found in Broadcasts or Chats")

async def update_user_preference(client_id, value):
    user_pref = value.get("user_preferences", [{}])[0]
    val = user_pref.get("value", "").lower()
    
    status = 0 if val == 'stop' else (1 if val == 'resume' else None)
    if status is None: return
    
    wa_id = user_pref.get("wa_id")
    phone_data = extract_phone_number(wa_id)
    
    timestamp = datetime.datetime.fromtimestamp(int(user_pref.get("timestamp")) if user_pref.get("timestamp") else time.time())
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Contact).where(
            Contact.client_id == client_id,
            Contact.country_code == phone_data['countryCode'],
            Contact.phone_number == phone_data['phoneNumber']
        ))
        contact = result.scalars().first()
        if contact:
            contact.status = status
            contact.status_updated_at = timestamp
            await session.commit()
