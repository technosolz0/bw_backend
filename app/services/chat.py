from app.database import AsyncSessionLocal
from app.models.sql_models import DailyStats, Chat, Message, Wallet, WalletHistory, Contact
from app.services.utils import get_secrets, get_base_url
from sqlalchemy.future import select
from sqlalchemy import update
import httpx
import os
import datetime
import logging
import random
import string
import time
import asyncio
import aiofiles

from datetime import timezone, timedelta

from app.services.firebase_service import sync_chat_metadata, sync_message
import uuid

logger = logging.getLogger(__name__)

def get_ist_time():
    return datetime.datetime.now(timezone(timedelta(hours=5, minutes=30)))

async def increment_daily_stats(client_id: str, date_str: str, type_str: str):
    async with AsyncSessionLocal() as session:
        try:
            # Check if stats exist for the day
            result = await session.execute(
                select(DailyStats).where(
                    DailyStats.client_id == client_id,
                    DailyStats.date == date_str
                )
            )
            stats = result.scalars().first()
            
            if not stats:
                stats = DailyStats(client_id=client_id, date=date_str)
                session.add(stats)
            
            if type_str == 'sent':
                if stats.total_sent is None:
                    stats.total_sent = 0
                stats.total_sent += 1
            elif type_str == 'delivered':
                if stats.total_delivered is None:
                    stats.total_delivered = 0
                stats.total_delivered += 1
            elif type_str == 'read':
                if stats.total_read is None:
                    stats.total_read = 0
                stats.total_read += 1
            elif type_str == 'failed':
                if stats.total_failed is None:
                    stats.total_failed = 0
                stats.total_failed += 1
                
            await session.commit()
            logger.info(f"📊 Daily stats updated for {date_str}: {type_str}")
        except Exception as e:
            logger.error(f"❌ Error updating daily stats: {e}")
            await session.rollback()

async def ensure_contact_and_chat(session, client_id, phone_number, chat_id=None, formatted_phone=None, name=None, country_code=None):
    """
    Ensures a contact and chat exist for the given phone number.
    Returns (contact_id, chat_name, phone_number)
    """
    if not formatted_phone:
        formatted_phone = phone_number.replace("+", "").replace(" ", "").replace("-", "")

    # 1. Determine Contact/Chat ID
    contact = None
    if chat_id and chat_id != "test":
        contact_res = await session.execute(
            select(Contact).where(Contact.id == chat_id, Contact.client_id == client_id)
        )
        contact = contact_res.scalars().first()
    
    if not contact:
        contact_res = await session.execute(
            select(Contact).where(Contact.client_id == client_id, Contact.phone_number == phone_number)
        )
        contact = contact_res.scalars().first()
    
    if contact:
        contact_id = contact.id
    else:
        contact_id = chat_id if (chat_id and chat_id != "test") else str(uuid.uuid4())
        contact = Contact(
            id=contact_id,
            client_id=client_id,
            phone_number=phone_number,
            country_code=country_code,
            f_name=name or "",
            l_name="",
            created_at=get_ist_time()
        )
        session.add(contact)
        await session.flush()

    effective_chat_id = contact_id
    
    # 2. Ensure Chat exists
    chat_res = await session.execute(
        select(Chat).where(Chat.client_id == client_id, Chat.id == effective_chat_id)
    )
    chat = chat_res.scalars().first()
    
    if not chat:
        chat = Chat(
            id=effective_chat_id,
            client_id=client_id,
            contact_id=contact_id,
            phone_number=phone_number,
            name=name or formatted_phone,
            is_active=True,
            un_read=False,
            created_at=get_ist_time()
        )
        session.add(chat)
    
    return effective_chat_id, chat.name, phone_number

async def create_template_chat_message(client_id, template, message, broadcast, whatsapp_message_id, status, status_timestamp):
    # template is now SQL model, message is BroadcastMessage model (or dict), broadcast is Broadcast model (optional)
    
    payload = message.payload if hasattr(message, 'payload') else (message.get('payload') if isinstance(message, dict) else {})
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
    
    sender_name = broadcast.admin_name if broadcast else "Admin"
    
    base_msg = {
        "is_from_me": True,
        "sender_name": sender_name,
        "status": status,
        "whatsapp_message_id": whatsapp_message_id,
        "sender_avatar": None,
        "caption": None,
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
        
        # message_id_val could be from model or dict
        def get_msg_val(obj, key):
            if hasattr(obj, key): return getattr(obj, key)
            if isinstance(obj, dict): return obj.get(key)
            return None

        attachment_id = broadcast.attachment_id if broadcast else get_msg_val(message, 'attachment_id')
        
        media_url = None
        if file_name and attachment_id:
            # Local File Storage URL
            dir_rel_path = f"broadcasts_media/{client_id}/{attachment_id}"
            server_url = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
            media_url = f"{server_url}/static/{dir_rel_path}/{file_name}"

        base_msg.update({
            "content": content,
            "file_name": file_name,
            "media_url": media_url,
            "message_type": header_vars.get("type", "").lower() if header_vars.get("type") else "image"
        })
        template_message = base_msg
        
    elif payload_type == 'INTERACTIVE':
        # simplifying interactive checks
        header_vars = payload.get("headerVariables", {})
        media_url = None
        file_name = None
        
        if header_vars:
             if header_vars.get("type") not in ['text', None]:
                file_name = header_vars.get("data", {}).get("fileName")
                attachment_id = broadcast.attachment_id if broadcast else get_msg_val(message, 'attachment_id')
                if file_name and attachment_id:
                    dir_rel_path = f"broadcasts_media/{client_id}/{attachment_id}"
                    server_url = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
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

async def send_whatsapp_message_helper(request_body: dict):
    try:
        client_id = request_body.get('clientId')
        phone_number = request_body.get('phoneNumber')
        message = request_body.get('message')
        chat_id = request_body.get('chatId')
        message_type = request_body.get('messageType')
        media_url = request_body.get('mediaUrl')
        file_name = request_body.get('fileName')
        caption = request_body.get('caption')

        secrets = await get_secrets(client_id)
        if not secrets:
            return {
                "statusCode": 404,
                "success": False,
                "message": "Client secrets not found"
            }

        if not phone_number or (not message and not media_url):
            return {
                "success": False,
                "message": "Phone number and message/media are required",
            }

        formatted_phone = phone_number.replace("+", "").replace(" ", "").replace("-", "")

        payload = {
            "messaging_product": "whatsapp",
            "to": formatted_phone,
        }

        message_content = message
        media_type = message_type or "text"

        if media_type == "text":
            payload["type"] = "text"
            payload["text"] = {"body": message}
        elif media_type == "image":
            payload["type"] = "image"
            payload["image"] = {"link": media_url}
            if caption:
                payload["image"]["caption"] = caption
            message_content = caption or "📷 Image"
        elif media_type == "document":
            payload["type"] = "document"
            payload["document"] = {
                "link": media_url,
                "filename": file_name or "document.pdf",
            }
            if caption:
                payload["document"]["caption"] = caption
            message_content = caption or f"📄 {file_name or 'Document'}"

        logger.info(f"Sending WhatsApp message: {payload}")

        base_url = get_base_url()
        token = os.getenv("META_TOKEN") or os.getenv("INTERAKT_TOKEN")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        url = f"{base_url}/{secrets.get('phoneNumberId')}/messages"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        whatsapp_message_id = data.get("messages", [{}])[0].get("id")

        # 📊 NEW: Increment sent count
        today = get_ist_time().strftime("%Y-%m-%d")
        await increment_daily_stats(client_id, today, "sent")
        logger.info(f"📊 Incremented sent count for {today}")


        async with AsyncSessionLocal() as session:
            effective_chat_id, chat_name, _ = await ensure_contact_and_chat(
                session, client_id, phone_number, chat_id, formatted_phone
            )
            
            # Re-fetch chat to update last message
            chat_res = await session.execute(
                select(Chat).where(Chat.client_id == client_id, Chat.id == effective_chat_id)
            )
            chat = chat_res.scalars().first()
            
            # 3. Create Message
            new_msg = Message(
                chat_id=effective_chat_id,
                client_id=client_id,
                content=message_content,
                timestamp=get_ist_time(),
                is_from_me=True,
                sender_name="Admin",
                status="sent",
                whatsapp_message_id=whatsapp_message_id,
                message_type=media_type,
                media_url=media_url,
                file_name=file_name,
                caption=caption
            )
            session.add(new_msg)
            
            # Update Chat last message
            if chat:
                chat.last_message = message_content
                chat.last_message_time = get_ist_time()
            
            await session.commit()

            # Firestore Sync - Chat & Message
            try:
                print(f"DEBUG: Starting Firestore sync for {effective_chat_id}")
                await sync_chat_metadata(effective_chat_id, client_id, {
                    "lastMessage": message_content,
                    "lastMessageTime": get_ist_time(),
                    "phoneNumber": phone_number,
                    "name": chat_name
                })
                
                await sync_message(effective_chat_id, client_id, whatsapp_message_id, {
                    "content": message_content,
                    "timestamp": get_ist_time(),
                    "isFromMe": True,
                    "senderName": "Admin",
                    "status": "sent",
                    "whatsappMessageId": whatsapp_message_id,
                    "messageType": media_type,
                    "mediaUrl": media_url,
                    "fileName": file_name,
                    "caption": caption
                })
                print(f"✅ Successfully stored in Firebase: Message {whatsapp_message_id}")
                logger.info(f"✅ Successfully stored in Firebase: Message {whatsapp_message_id}")
            except Exception as fe:
                print(f"DEBUG: ❌ Firebase Sync Error in chat.py: {fe}")
                logger.error(f"❌ Firebase Sync Error: {fe}")

        return {
            "statusCode": 200,
            "success": True,
            "data": data,
            "messageId": whatsapp_message_id,
        }

    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response'):
            error_msg = e.response.text
        logger.error(f"INTERAKT ERROR: {error_msg}")
        return {
            "statusCode": 500,
            "success": False,
            "message": error_msg,
        }

async def mark_message_as_read(secrets, message_id, add_typing_indicator=False):
    try:
        base_url = get_base_url()
        token = os.getenv("META_TOKEN") or os.getenv("INTERAKT_TOKEN")
        
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        if add_typing_indicator:
            payload["typing_indicator"] = {
                "type": "text"
            }
            
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{base_url}/{secrets['phoneNumberId']}/messages",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
            )
        logger.info("Message marked as read successfully.")
    except Exception as e:
        logger.error(f"Error marking message as read: {e}")
        # throw error ? or just log
        raise e

async def refund_message_cost(client_id, broadcast_id, cost):
    async with AsyncSessionLocal() as session:
        try:
            # Update Wallet
            wallet_result = await session.execute(select(Wallet).where(Wallet.client_id == client_id))
            wallet = wallet_result.scalars().first()
            if wallet:
                wallet.balance += cost
            
            # Update History
            history_result = await session.execute(
                select(WalletHistory)
                .where(WalletHistory.broadcast_id == broadcast_id, WalletHistory.client_id == client_id)
            )
            history = history_result.scalars().first() # Assuming one history entry per broadcast
            if history:
                history.chargeable_messages -= 1
                history.chargeable_amount -= cost
                
            await session.commit()
        except Exception as e:
            logger.error(f"Error refunding message cost: {e}")
            await session.rollback()

async def download_and_upload_media(client_id, secrets, media_id, mime_type, original_filename=None, message_id=None):
    max_retries = 2
    base_url = get_base_url()
    token = os.getenv("META_TOKEN") or os.getenv("INTERAKT_TOKEN")
    
    # Get server URL and ensure no trailing slash
    server_url = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
    
    last_error = None
    
    for retry in range(max_retries + 1):
        try:
            logger.info(f"[Media {media_id}] Attempt {retry + 1}: Fetching signed URL...")
            
            async with httpx.AsyncClient(follow_redirects=True) as client:
                # 1. Get the media metadata (includes the URL)
                meta_res = await client.get(
                    f"{base_url}/{media_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=20.0 + (retry * 5)
                )
                meta_res.raise_for_status()
                signed_url = meta_res.json().get("url")
                
                if not signed_url:
                    raise ValueError(f"No signed URL in response: {meta_res.text}")
                
                logger.info(f"[Media {media_id}] Signed URL fetched. Downloading content...")
                
                # 2. Download the actual content
                # Note: Sometimes Meta signed URLs don't want the Authorization header.
                # We'll try with it first, then without if it fails.
                try:
                    download_res = await client.get(
                        signed_url,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=90.0 + (retry * 10)
                    )
                    download_res.raise_for_status()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in [401, 403]:
                        logger.warning(f"[Media {media_id}] Auth failed on CDNs, retrying without Authorization header...")
                        download_res = await client.get(
                            signed_url,
                            timeout=90.0 + (retry * 10)
                        )
                        download_res.raise_for_status()
                    else:
                        raise e

                buffer = download_res.content
                file_size = len(buffer)
                
                # Check if we got an error page instead of an image
                content_type = download_res.headers.get("Content-Type", "").lower()
                if "text/html" in content_type or "application/json" in content_type:
                    logger.error(f"[Media {media_id}] Downloaded unexpected content type: {content_type}")
                    raise ValueError(f"Downloaded {content_type} instead of binary media")

                if file_size < 100: # Files too small are likely errors
                     raise ValueError(f"Downloaded file too small: {file_size} bytes")
                
                logger.info(f"[Media {media_id}] Downloaded {file_size} bytes ({content_type})")
                
                # Determine extension
                ext = mime_type.split("/")[1].split("+")[0] if mime_type else None
                if not ext:
                    # Fallback to content type from download
                    ext = content_type.split("/")[1] if "/" in content_type else "file"
                
                timestamp = int(time.time() * 1000)
                random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
                
                safe_original = None
                if original_filename:
                    safe_original = "".join([c if c.isalnum() or c in "._-" else "_" for c in original_filename])
                
                final_filename = safe_original or f"{(message_id or media_id)[-8:]}_{timestamp}_{random_str}.{ext}"
                
                now = get_ist_time()
                year = now.year
                month = f"{now.month:02d}"
                
                # Local File Storage
                dir_rel_path = f"whatsapp_media/{client_id}/{year}/{month}"
                dir_path = os.path.join("static", dir_rel_path)
                os.makedirs(dir_path, exist_ok=True)
                
                file_path = os.path.join(dir_path, final_filename)
                
                async with aiofiles.open(file_path, 'wb') as f:
                    await f.write(buffer)
                
                public_url = f"{server_url}/static/{dir_rel_path}/{final_filename}"
                     
                logger.info(f"[Media {media_id}] ✅ Uploaded to: {public_url}")
                
                return {
                    "url": public_url,
                    "filename": original_filename or final_filename,
                    "mimeType": mime_type or content_type,
                    "size": file_size
                }

        except Exception as err:
            last_error = err
            logger.warning(f"[Media {media_id}] Attempt {retry + 1} failed: {err}")
            if retry < max_retries:
                await asyncio.sleep(2 * (retry + 1))
                
    logger.error(f"MEDIA DOWNLOAD FAILED (all retries): {last_error}")
    return None

async def upload_media_from_base64(client_id, file_name, mime_type, base64_file):
    try:
        import base64
        file_data = base64.b64decode(base64_file)
        
        dir_rel_path = f"chat_media/{client_id}"
        dir_path = os.path.join("static", dir_rel_path)
        os.makedirs(dir_path, exist_ok=True)
        
        timestamp = int(time.time() * 1000)
        final_filename = f"{timestamp}_{file_name}"
        file_path = os.path.join(dir_path, final_filename)
        
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_data)
        
        server_url = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
        public_url = f"{server_url}/static/{dir_rel_path}/{final_filename}"
        
        return {
            "success": True,
            "url": public_url,
            "fileName": file_name
        }
    except Exception as e:
        logger.error(f"Upload media error: {e}")
        raise e

async def update_message_status_manual(client_id, whatsapp_message_id, status):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Message)
                .join(Chat)
                .where(Chat.client_id == client_id, Message.whatsapp_message_id == whatsapp_message_id)
            )
            message = result.scalars().first()
            if message:
                message.status = status
                await session.commit()
                logger.info(f"Updated message {whatsapp_message_id} status to {status}")
                return True
            return False
        except Exception as e:
            logger.error(f"Update status error: {e}")
            raise e

async def get_daily_stats_helper(client_id, date_str):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(DailyStats).where(
                    DailyStats.client_id == client_id,
                    DailyStats.date == date_str
                )
            )
            stats = result.scalars().first()
            if not stats:
                 return {
                     "date": date_str,
                     "totalSent": 0,
                     "totalDelivered": 0,
                     "totalRead": 0
                 }
            return {
                "date": stats.date,
                "totalSent": stats.total_sent,
                "totalDelivered": stats.total_delivered,
                "totalRead": stats.total_read,
                "totalFailed": stats.total_failed
            }
        except Exception as e:
            logger.error(f"Error getting daily stats: {e}")
            raise e


