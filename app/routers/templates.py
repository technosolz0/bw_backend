from fastapi import APIRouter, Request, Response, UploadFile, File, Form
from app.services.whatsapp_meta import (
    get_meta_templates,
    delete_meta_template,
    create_meta_template,
    create_media_handle,
    create_media_id
)
from app.services.utils import get_secrets
from app.database import AsyncSessionLocal
from app.models.sql_models import Template
from sqlalchemy.future import select
import logging
import json

from app.schemas import TemplateCreate, DeleteTemplateRequest
from fastapi import Query

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/createInteraktTemplate")
async def create_template(body: TemplateCreate):
    try:
        data = body.dict(exclude_none=True)
        result = await create_meta_template(body.clientId, data) 
        
        if isinstance(result, dict) and "error" in result:
            return {"success": False, "error": result["error"]}
            
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        return {"success": False, "message": str(e)}


@router.get("/getInteraktTemplates")
async def get_templates(
    clientId: str = Query(None),
    limit: int = Query(None),
    after: str = Query(None),
    before: str = Query(None)
):
    try:
        if not clientId:
             return {"success": False, "message": "Missing clientId"}
             
        result = await get_meta_templates(
            clientId, 
            limit, 
            after, 
            before
        )
        
        if isinstance(result, dict) and "error" in result:
             return {"success": False, "error": result["error"]}
             
        return {"success": True, "data": result.get("data", result)}
    except Exception as e:
        logger.error(f"Error fetching templates: {e}")
        return {"success": False, "message": str(e)}


@router.get("/getApprovedTemplates")
async def get_approved(clientId: str = Query(...)):
    try:
        result = await get_meta_templates(clientId, status="APPROVED", fields="name,category")
        
        if isinstance(result, dict) and "error" in result:
             return {"success": False, "error": result["error"]}
             
        return {"success": True, "data": result.get("data", [])}
    except Exception as e:
        logger.error(f"Error fetching approved templates: {e}")
        return {"success": False, "message": str(e)}


@router.get("/getApprovedMediaTemplates")
async def get_approved_media(clientId: str = Query(...)):
    try:
        # Fetch name, category, and components from Meta API
        result = await get_meta_templates(clientId, status="APPROVED", fields="name,category,components")
        
        if isinstance(result, dict) and "error" in result:
             return {"success": False, "error": result["error"]}
             
        approved_templates = result.get("data", [])
        
        media_templates = []
        for t in approved_templates:
            components = t.get("components", [])
            # A template is considered a media template if it has a HEADER with IMAGE or VIDEO format
            has_media = False
            for comp in components:
                if comp.get("type") == "HEADER" and comp.get("format") in ["IMAGE", "VIDEO", "DOCUMENT"]:
                    has_media = True
                    break
            
            if has_media:
                media_templates.append(t)
                
        return {"success": True, "data": media_templates}
        
    except Exception as e:
        logger.error(f"Error fetching approved media templates: {e}")
        return {"success": False, "message": str(e)}


@router.post("/deleteInteraktTemplate")
async def delete_template(body: DeleteTemplateRequest):
    try:
        name = body.name
        client_id = body.clientId
        
        if not name or not client_id:
             return Response("Missing name or clientId", status_code=400)
             
        result = await delete_meta_template(client_id, name)
        return {"success": True, "message": "Template deleted successfully", "data": result}
    except Exception as e:
        return Response(content=str(e), status_code=500)

@router.post("/uploadMediaToInterakt")
async def upload_media_handle(
    clientId: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        secrets = await get_secrets(clientId)
        content = await file.read()
        handle = await create_media_handle(secrets, content, file.filename, file.content_type)
        return {"success": True, "media_handle_id": handle}
    except Exception as e:
        return Response(content=str(e), status_code=500)

@router.post("/uploadBroadcastMedia")
async def upload_media_id_endpoint(
    clientId: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        secrets = await get_secrets(clientId)
        content = await file.read()
        mid = await create_media_id(secrets, content, file.filename, file.content_type)
        return {"success": True, "media_id": mid}
    except Exception as e:
        return Response(content=str(e), status_code=500)
