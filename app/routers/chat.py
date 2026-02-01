from fastapi import APIRouter, Response, HTTPException, Query, Body
from app.services.chat import (
    send_whatsapp_message_helper,
    upload_media_from_base64,
    update_message_status_manual,
    get_daily_stats_helper
)
import logging

from app.schemas import SendMessageRequest, UploadMediaRequest, UpdateMessageStatusRequest

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/sendWhatsAppMessage")
async def send_whatsapp_message(body: SendMessageRequest = Body(...)):
    try:
        # Service expects dict? Or modify service to accept object?
        # Service `send_whatsapp_message_helper` usually takes a dict.
        # body.dict() handles it.
        response = await send_whatsapp_message_helper(body.dict(exclude_none=True))
        status = response.get("statusCode", 200)
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
        return {"success": True}
    except Exception as e:
        return Response(content=str(e), status_code=500)

@router.get("/getDailyStats")
async def get_daily_stats_endpoint(
    clientId: str = Query(...), 
    date: str = Query(...)
):
    client_id = clientId
        
    try:
        data = await get_daily_stats_helper(client_id, date)
        return {"success": True, "data": data}
    except Exception as e:
        return Response(content=str(e), status_code=500)
