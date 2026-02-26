from fastapi import APIRouter, Request, Response, BackgroundTasks, Body, Query
from app.services.broadcasts import start_broadcast, create_broadcast_record
from app.services.whatsapp_meta import get_secrets
from app.database import AsyncSessionLocal
from app.models.sql_models import Broadcast, BroadcastMessage
from sqlalchemy.future import select
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

from app.schemas import BroadcastStartRequest, BroadcastCreateRequest, SendTemplateMessageRequest

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
