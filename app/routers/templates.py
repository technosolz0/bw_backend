from fastapi import APIRouter, Request, Response, UploadFile, File, Form
from app.services.interakt import (
    create_interakt_template,
    get_interakt_templates,
    delete_interakt_template,
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
        # Convert Pydantic model to dict for service layer if needed, or pass fields
        # usage: create_interakt_template(client_id, template_data)
        # We can pass body.dict() or similar.
        data = body.dict(exclude_none=True)
        # Note: templateType vs type in older code? schema has templateType. 
        result = await create_interakt_template(body.clientId, data) 
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        return Response(content=str(e), status_code=500)

@router.get("/getInteraktTemplates")
@router.get("/getInteraktTemplates")
async def get_templates(
    clientId: str = Query(None),
    limit: int = Query(None),
    after: str = Query(None),
    before: str = Query(None)
):
    try:
        if not clientId:
             return Response("Missing clientId", status_code=400)
             
        result = await get_interakt_templates(
            clientId, 
            limit, 
            after, 
            before
        )
        return {"success": result.get("success", True), "data": result.get("data", result)}
    except Exception as e:
        return Response(content=str(e), status_code=500)

@router.get("/getApprovedTemplates")
@router.get("/getApprovedTemplates")
async def get_approved(clientId: str = Query(...)):
    try:
        result = await get_interakt_templates(clientId, status="APPROVED", fields="name,category")
        return {"success": True, "data": result.get("data", [])}
    except Exception as e:
        return Response(content=str(e), status_code=500)

@router.get("/getApprovedMediaTemplates")
@router.get("/getApprovedMediaTemplates")
async def get_approved_media(clientId: str = Query(...)):
    try:
        client_id = clientId
        result = await get_interakt_templates(client_id, status="APPROVED", fields="name,category")
        approved_templates = result.get("data", [])
        
        # Database filter
        async with AsyncSessionLocal() as session:
            db_res = await session.execute(
                select(Template).where(
                     Template.client_id == client_id,
                     Template.type == "Text & Media"
                )
            )
            templates = db_res.scalars().all()
            
            media_template_ids = set()
            for t in templates:
                comps = t.components or []
                if comps and isinstance(comps, list) and len(comps) > 0:
                     if comps[0].get("format") == "IMAGE":
                         media_template_ids.add(t.id)
        
        filtered = [t for t in approved_templates if t.get("id") in media_template_ids]
        return {"success": True, "data": filtered}
        
    except Exception as e:
        return Response(content=str(e), status_code=500)

@router.post("/deleteInteraktTemplate")
@router.post("/deleteInteraktTemplate")
async def delete_template(body: DeleteTemplateRequest):
    try:
        name = body.name
        client_id = body.clientId
        
        if not name or not client_id:
             return Response("Missing name or clientId", status_code=400)
             
        result = await delete_interakt_template(client_id, name)
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
