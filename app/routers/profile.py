from fastapi import APIRouter, Request, Response, UploadFile, File, Form
from app.services.whatsapp_meta import (
    get_whatsapp_business_profile,
    update_whatsapp_business_profile,
    create_media_handle
)
from app.services.utils import get_secrets
import logging
import json

router = APIRouter()
logger = logging.getLogger(__name__)

from fastapi import Query

@router.get("/getWhatsAppBusinessProfile")
async def get_profile(clientId: str = Query(...)):
    client_id = clientId
    
    try:
        data = await get_whatsapp_business_profile(client_id)
        return {"success": True, "data": [data]}
    except Exception as e:
        logger.error(f"Error getting profile: {e}")
        return Response(content=str(e), status_code=500)

@router.post("/updateWhatsAppBusinessProfile")
async def update_profile(
    client_id: str = Form(...),
    about: str = Form(None),
    address: str = Form(None),
    description: str = Form(None),
    email: str = Form(None),
    vertical: str = Form(None),
    websites: str = Form(None),
    file: UploadFile = File(None)
):
    try:
        secrets = await get_secrets(client_id)
        media_handle = None
        
        if file:
            content = await file.read()
            media_handle = await create_media_handle(secrets, content, file.filename, file.content_type)
            
        payload = {}
        if about: payload["about"] = about
        if address: payload["address"] = address
        if description: payload["description"] = description
        if email: payload["email"] = email
        if vertical: payload["vertical"] = vertical
        if websites:
            # websites might be JSON string or list
            try:
                payload["websites"] = json.loads(websites)
            except:
                payload["websites"] = [websites]
        
        if media_handle:
            payload["profile_picture_handle"] = media_handle
            
        result = await update_whatsapp_business_profile(client_id, payload)
        return result
        
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        return Response(content=str(e), status_code=500)

@router.patch("/patchWhatsAppBusinessProfile")
async def patch_profile(
    client_id: str = Form(...),
    about: str = Form(None),
    address: str = Form(None),
    description: str = Form(None),
    email: str = Form(None),
    vertical: str = Form(None),
    websites: str = Form(None),
    file: UploadFile = File(None)
):
    try:
        secrets = await get_secrets(client_id)
        media_handle = None
        
        if file:
            content = await file.read()
            media_handle = await create_media_handle(secrets, content, file.filename, file.content_type)
            
        payload = {}
        if about is not None: payload["about"] = about
        if address is not None: payload["address"] = address
        if description is not None: payload["description"] = description
        if email is not None: payload["email"] = email
        if vertical is not None: payload["vertical"] = vertical
        if websites is not None:
            try:
                payload["websites"] = json.loads(websites)
            except:
                payload["websites"] = [websites]
        
        if media_handle:
            payload["profile_picture_handle"] = media_handle
            
        if not payload:
            return {"success": True, "message": "No fields to update"}
            
        result = await update_whatsapp_business_profile(client_id, payload)
        return result
        
    except Exception as e:
        logger.error(f"Error patching profile: {e}")
        return Response(content=str(e), status_code=500)
