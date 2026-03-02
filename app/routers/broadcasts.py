from fastapi import APIRouter, Request, Response, BackgroundTasks, Body, Query, HTTPException
from app.services.broadcasts import start_broadcast, create_broadcast_record
from app.services.whatsapp_meta import get_secrets
from app.database import AsyncSessionLocal
from app.models.sql_models import Broadcast, BroadcastMessage
from sqlalchemy.future import select
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

from app.schemas import BroadcastStartRequest, BroadcastCreateRequest, SendTemplateMessageRequest, BroadcastUpdate
from app.services.firebase_service import sync_broadcast_stats, sync_chat_metadata, sync_message
from app.services.chat import ensure_contact_and_chat, create_template_chat_message, increment_daily_stats, get_ist_time
from app.models.sql_models import Broadcast, BroadcastMessage, Template, Message, Chat

@router.post("/sendTemplateMessage")
async def send_template_message_endpoint(body: SendTemplateMessageRequest):
    try:
        client_id = body.clientId
        secrets = await get_secrets(client_id)
        if not secrets:
            return Response(content="Client secrets not found", status_code=404)
        
        # Extract variables
        body_vars = body.bodyVariables
        media_id = body.mediaId
        media_type = body.mediaType or "image"
        header_text = body.headerText
        button_payloads = None
        
        # If headerVariables is provided (matching broadcastHandler.js format)
        if body.headerVariables:
            h_type = body.headerVariables.get("type")
            h_data = body.headerVariables.get("data", {})
            if h_type == "text":
                header_text = h_data.get("text")
            else:
                media_id = h_data.get("mediaId")
                media_type = h_type
        
        if body.buttonVariables:
            button_payloads = [b.get("payload") for b in body.buttonVariables if b.get("payload")]

        from app.services.whatsapp_meta import send_template_message
        response = await send_template_message(
            client_id=client_id,
            secrets=secrets,
            template_name=body.templateName,
            language=body.language,
            body_vars=body_vars,
            media_id=media_id,
            phone_number=body.phoneNumber,
            header_text=header_text,
            media_type=media_type,
            button_payloads=button_payloads
        )
        
        whatsapp_message_id = response.get("messages", [{}])[0].get("id")
        
        # 📊 Persist to Message Table & Sync to Firestore
        async with AsyncSessionLocal() as session:
            try:
                # 1. Get Template record
                t_res = await session.execute(select(Template).where(Template.name == body.templateName, Template.client_id == client_id))
                template_record = t_res.scalars().first()
                
                if template_record:
                    # 2. Use helper to find/create Contact and Chat
                    effective_chat_id, chat_name, _ = await ensure_contact_and_chat(
                        session, client_id, body.phoneNumber, name=None
                    )
                    
                    # 3. Create the template-formatted message
                    # Consolidate payload for create_template_chat_message
                    payload = {
                        "type": body.mediaType.upper() if body.mediaId else "TEXT",
                        "bodyVariables": body_vars or [],
                        "headerVariables": body.headerVariables or ({
                            "type": media_type,
                            "data": {"mediaId": media_id, "text": header_text}
                        } if (media_id or header_text) else None)
                    }
                    
                    template_chat_msg = await create_template_chat_message(
                        client_id,
                        template_record,
                        {"payload": payload}, # Pass as dict since create_template_chat_message handles it
                        None, # No broadcast object
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
                        
                        await session.commit()
                        
                        # 6. Firestore Sync
                        await sync_chat_metadata(effective_chat_id, client_id, {
                            "lastMessage": template_chat_msg.get("content", ""),
                            "lastMessageTime": get_ist_time(),
                            "phoneNumber": body.phoneNumber,
                            "name": chat_name
                        })
                        
                        await sync_message(effective_chat_id, client_id, whatsapp_message_id, {
                            "content": template_chat_msg.get("content", ""),
                            "timestamp": get_ist_time(),
                            "isFromMe": True,
                            "senderName": "Admin",
                            "status": "sent",
                            "whatsappMessageId": whatsapp_message_id,
                            "messageType": template_chat_msg.get("message_type", "text"),
                            "mediaUrl": template_chat_msg.get("media_url"),
                            "fileName": template_chat_msg.get("file_name")
                        })
                        logger.info(f"✅ Template message {whatsapp_message_id} persisted and synced for {body.phoneNumber}")
                else:
                    logger.warning(f"Template {body.templateName} not found in DB, skipping persistence")
            except Exception as persistence_err:
                logger.error(f"Failed to persist template message: {persistence_err}")
                await session.rollback()

        # Update stats
        today = get_ist_time().strftime("%Y-%m-%d")
        await increment_daily_stats(client_id, today, 'sent')
        
        return {"success": True, "data": response}
    except Exception as e:
        logger.error(f"Error sending template message: {e}")
        return Response(content=str(e), status_code=500)

@router.post("/startBroadcast")
async def start_broadcast_endpoint(body: BroadcastStartRequest):
    try:
        client_id = body.clientId
        broadcast_id = body.broadcastId
        
        result = await start_broadcast(client_id, broadcast_id)
        return result
    except Exception as e:
        logger.error(f"Error starting broadcast: {e}")
        return Response(content=str(e), status_code=500)

@router.post("/createBroadcast")
async def create_broadcast_endpoint(body: BroadcastCreateRequest):
    try:
        client_id = body.clientId
        
        broadcast_id = await create_broadcast_record(client_id, body.dict(exclude_none=True))
        return {"success": True, "broadcastId": broadcast_id}
    except Exception as e:
        logger.error(f"Error creating broadcast: {e}")
        return Response(content=str(e), status_code=500)

@router.patch("/patchBroadcast")
async def patch_broadcast(broadcastId: str = Query(...), body: BroadcastUpdate = Body(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                 select(Broadcast).where(Broadcast.id == broadcastId)
            )
            broadcast = result.scalars().first()
            if not broadcast:
                raise HTTPException(status_code=404, detail="Broadcast not found")
            
            for key, value in body.dict(exclude_none=True).items():
                setattr(broadcast, key, value)
            
            await session.commit()
            
            # Firestore Sync
            await sync_broadcast_stats(broadcastId, broadcast.client_id, {
                "sent": broadcast.sent,
                "delivered": broadcast.delivered,
                "read": broadcast.read,
                "failed": broadcast.failed,
                "status": broadcast.status
            })
            
            return {"success": True}
        except Exception as e:
            logger.error(f"Error patching broadcast: {e}")
            return Response(content=str(e), status_code=500)

@router.get("/getBroadcasts")
async def get_broadcasts(clientId: str):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                 select(Broadcast).where(Broadcast.client_id == clientId).order_by(Broadcast.created_at.desc())
            )
            broadcasts = result.scalars().all()
            return {"success": True, "data": broadcasts}
        except Exception as e:
            return Response(content=str(e), status_code=500)

@router.get("/getBroadcastDetails")
async def get_broadcast_details(broadcastId: str):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                 select(Broadcast).where(Broadcast.id == broadcastId)
            )
            broadcast = result.scalars().first()
            
            msg_result = await session.execute(
                 select(BroadcastMessage).where(BroadcastMessage.broadcast_id == broadcastId)
            )
            messages = msg_result.scalars().all()
            
            return {
                "success": True, 
                "broadcast": broadcast,
                "messages": messages
            }
        except Exception as e:
            return Response(content=str(e), status_code=500)
