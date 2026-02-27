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
import logging

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

        # headers = {
        #     "x-access-token": token,
        #     "x-waba-id": secrets.get("wabaId"),
        #     "Content-Type": "application/json",
        # }
        # JS code used INTERAKT_TOKEN from env, but secrets also has it?
        # In JS: const INTERAKT_TOKEN = process.env.INTERAKT_TOKEN;
        # But wait, utils.js doesn't return INTERAKT_TOKEN in secrets?
        # utils.js secrets: wabaId, phoneNumberId, phoneNumber, webhookVerifyToken, storeId, qnaStoreId, googleApiKey.
        # It DOES NOT return interakt token.
        # So we must get it from env.
        
        # interakt_token = os.getenv("INTERAKT_TOKEN")
        # headers["x-access-token"] = interakt_token

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
            # 1. Determine Contact/Chat ID
            # Priority: 
            # a) Use existing contact for this phone number
            # b) Use provided chat_id if given (and potentially link to contact)
            # c) Generate new UUID
            
            contact_res = await session.execute(
                select(Contact).where(Contact.client_id == client_id, Contact.phone_number == phone_number)
            )
            contact = contact_res.scalars().first()
            
            if contact:
                contact_id = contact.id
            else:
                # If we have a chat_id but no contact, we might use chat_id as contact_id for new contact
                # if it looks like a UUID or a custom string.
                # But for consistency with webhooks:
                contact_id = chat_id if (chat_id and chat_id != "test") else str(uuid.uuid4())
                contact = Contact(
                    id=contact_id,
                    client_id=client_id,
                    phone_number=phone_number,
                    f_name="",
                    l_name="",
                    created_at=get_ist_time()
                )
                session.add(contact)
                await session.flush()

            # The chatId in this system is typically the contactId
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
                    name=formatted_phone,
                    is_active=True,
                    un_read=False,
                    created_at=get_ist_time()
                )
                session.add(chat)
            
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
            chat.last_message = message_content
            chat.last_message_time = get_ist_time()
            
            await session.commit()

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
    
    last_error = None
    
    for retry in range(max_retries + 1):
        try:
            logger.info(f"[Media {media_id}] Attempt {retry + 1}: Fetching signed URL...")
            
            async with httpx.AsyncClient() as client:
                meta_res = await client.get(
                    f"{base_url}/{media_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=20.0 + (retry * 5)
                )
                meta_res.raise_for_status()
                signed_url = meta_res.json().get("url")
                
                if not signed_url:
                    raise ValueError(f"No signed URL in response: {meta_res.text}")
                
                logger.info(f"[Media {media_id}] Signed URL fetched.")
                
                download_res = await client.get(
                    signed_url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=90.0 + (retry * 10)
                )
                download_res.raise_for_status()
                buffer = download_res.content
                file_size = len(buffer)
                
                if file_size == 0:
                     raise ValueError("Downloaded empty file")
                
                logger.info(f"[Media {media_id}] Downloaded {file_size} bytes")
                
                ext = mime_type.split("/")[1].split("+")[0] if mime_type else "file"
                if not ext: ext = "file"
                
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
                
                server_url = os.getenv("SERVER_URL", "http://localhost:8000")
                public_url = f"{server_url}/static/{dir_rel_path}/{final_filename}"
                     
                logger.info(f"[Media {media_id}] ✅ Uploaded to: {public_url}")
                
                return {
                    "url": public_url,
                    "filename": original_filename or final_filename,
                    "mimeType": mime_type,
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
        
        server_url = os.getenv("SERVER_URL", "http://localhost:8000")
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


