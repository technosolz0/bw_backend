from fastapi import APIRouter, Request, Response, BackgroundTasks
from app.services.broadcasts import start_broadcast, create_broadcast_record
from app.database import AsyncSessionLocal
from app.models.sql_models import Broadcast, BroadcastMessage
from sqlalchemy.future import select
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/startBroadcast")
async def start_broadcast_endpoint(request: Request):
    try:
        body = await request.json()
        client_id = body.get("clientId")
        broadcast_id = body.get("broadcastId")
        
        if not client_id or not broadcast_id:
             return Response("Missing clientId or broadcastId", status_code=400)
             
        result = await start_broadcast(client_id, broadcast_id)
        return result
    except Exception as e:
        logger.error(f"Error starting broadcast: {e}")
        return Response(content=str(e), status_code=500)

@router.post("/createBroadcast")
async def create_broadcast_endpoint(request: Request):
    try:
        body = await request.json()
        client_id = body.get("clientId")
        
        if not client_id:
             return Response("Missing clientId", status_code=400)
             
        broadcast_id = await create_broadcast_record(client_id, body)
        return {"success": True, "broadcastId": broadcast_id}
    except Exception as e:
        logger.error(f"Error creating broadcast: {e}")
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
