from fastapi import APIRouter, Response, HTTPException, Query, Body, WebSocket, WebSocketDisconnect
from app.services.chat import (
    send_whatsapp_message_helper,
    upload_media_from_base64,
    update_message_status_manual,
    get_daily_stats_helper
)
from app.services.websocket_manager import manager
from app.database import AsyncSessionLocal
from app.models.sql_models import Chat, Message as MessageModel
from sqlalchemy.future import select
from sqlalchemy import desc
import logging
import json

from app.schemas import SendMessageRequest, UploadMediaRequest, UpdateMessageStatusRequest, UpdateChatRequest

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/updateChat")
async def update_chat_endpoint(body: UpdateChatRequest = Body(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Chat).where(Chat.id == body.chatId, Chat.client_id == body.clientId)
            )
            chat = result.scalars().first()
            if not chat:
                raise HTTPException(status_code=404, detail="Chat not found")
            
            if body.isActive is not None:
                chat.is_active = body.isActive
            if body.unRead is not None:
                chat.un_read = body.unRead
            if body.isFavourite is not None:
                # Assuming is_favourite exists in model or handle it
                # If it doesn't exist, we might need to add it to SQL model
                chat.is_favourite = body.isFavourite
            if body.assignedAdmins is not None:
                chat.assigned_admins = body.assignedAdmins
                
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating chat: {e}")
            return Response(content=str(e), status_code=500)

@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(client_id, websocket)
    try:
        while True:
            # We can receive messages if needed, but currently just broadcasting updates
            data = await websocket.receive_text()
            # Handle incoming WS messages if necessary
    except WebSocketDisconnect:
        manager.disconnect(client_id, websocket)

@router.get("/getChats")
async def get_chats(clientId: str = Query(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Chat)
                .where(Chat.client_id == clientId)
                .order_by(desc(Chat.last_message_time))
            )
            chats = result.scalars().all()
            return {"success": True, "data": chats}
        except Exception as e:
            logger.error(f"Error fetching chats: {e}")
            return Response(content=str(e), status_code=500)

@router.post("/createChat")
async def create_chat(body: UpdateChatRequest = Body(...)): # Reusing UpdateChatRequest or similar
    async with AsyncSessionLocal() as session:
        try:
            # Note: client_id and contact_id are required
            result = await session.execute(
                select(Contact).where(Contact.id == body.chatId, Contact.client_id == body.clientId)
            )
            contact = result.scalars().first()
            if not contact:
                raise HTTPException(status_code=404, detail="Contact not found")
            
            # Create chat
            new_chat = Chat(
                id=body.chatId,
                client_id=body.clientId,
                contact_id=body.chatId,
                name=f"{contact.f_name or ''} {contact.l_name or ''}".strip(),
                phone_number=contact.phone_number,
                last_message="",
                last_message_time=func.now()
            )
            session.add(new_chat)
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error creating chat: {e}")
            return Response(content=str(e), status_code=500)

@router.delete("/deleteChat")
async def delete_chat(chatId: str = Query(...), clientId: str = Query(...)):
    async with AsyncSessionLocal() as session:
        try:
            # Delete messages first
            await session.execute(
                MessageModel.__table__.delete().where(
                    MessageModel.chat_id == chatId, 
                    MessageModel.client_id == clientId
                )
            )
            # Delete chat
            await session.execute(
                Chat.__table__.delete().where(
                    Chat.id == chatId, 
                    Chat.client_id == clientId
                )
            )
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting chat: {e}")
            return Response(content=str(e), status_code=500)

@router.get("/getAdmins")
async def get_admins(clientId: str = Query(...)):
    from app.models.sql_models import Admin
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Admin).where(Admin.client_id == clientId)
            )
            admins = result.scalars().all()
            return {"success": True, "data": admins}
        except Exception as e:
            logger.error(f"Error fetching admins: {e}")
            return Response(content=str(e), status_code=500)

@router.get("/getMessages")
async def get_messages(
    chatId: str = Query(...),
    clientId: str = Query(...),
    limit: int = Query(20),
    offset: int = Query(0)
):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(MessageModel)
                .where(MessageModel.chat_id == chatId, MessageModel.client_id == clientId)
                .order_by(desc(MessageModel.timestamp))
                .limit(limit)
                .offset(offset)
            )
            messages = result.scalars().all()
            return {"success": True, "data": messages}
        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            return Response(content=str(e), status_code=500)

@router.post("/sendWhatsAppMessage")
async def send_whatsapp_message(body: SendMessageRequest = Body(...)):
    try:
        response = await send_whatsapp_message_helper(body.dict(exclude_none=True))
        status = response.get("statusCode", 200)
        
        # Broadcast the sent message to all listeners for this client
        if response.get("success"):
            # We don't have the full message object here easily without querying?
            # Actually, the frontend optimistically adds it, but for multi-admin sync:
            await manager.broadcast_to_client(body.clientId, {
                "type": "message_sent",
                "chatId": body.chatId,
                "messageId": response.get("messageId")
            })

        from fastapi.responses import JSONResponse
        return JSONResponse(content={
            "success": response.get("success"),
            "data": response.get("data"),
            "message": response.get("message")
        }, status_code=status)
    except Exception as e:
        return Response(content=str(e), status_code=500)

@router.post("/uploadMediaForChat")
async def upload_media(body: UploadMediaRequest = Body(...)):
    try:
        client_id = body.clientId
        file_name = body.fileName
        mime_type = body.mimeType
        base64_file = body.base64File
        
        result = await upload_media_from_base64(client_id, file_name, mime_type, base64_file)
        return result
    except Exception as e:
        return Response(content=str(e), status_code=500)

@router.post("/updateMessageStatus")
async def update_status_endpoint(body: UpdateMessageStatusRequest = Body(...)):
    try:
        client_id = body.clientId
        whatsapp_message_id = body.whatsappMessageId
        status = body.status
        
        await update_message_status_manual(client_id, whatsapp_message_id, status)
        
        # Broadcast status update
        await manager.broadcast_to_client(client_id, {
            "type": "status_update",
            "whatsappMessageId": whatsapp_message_id,
            "status": status
        })
        
        return {"success": True}
    except Exception as e:
        return Response(content=str(e), status_code=500)

@router.get("/getDailyStats")
async def get_daily_stats_endpoint(
    clientId: str = Query(...), 
    date: str = Query(...)
):
    try:
        data = await get_daily_stats_helper(clientId, date)
        return {"success": True, "data": data}
    except Exception as e:
        return Response(content=str(e), status_code=500)
