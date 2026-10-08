from fastapi import APIRouter, Request, Response, UploadFile, File, Form
from fastapi.responses import JSONResponse
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

from typing import Dict, Any
from app.schemas import TemplateCreate, DeleteTemplateRequest
from fastapi import Query, Body

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/createInteraktTemplate")
async def create_template(body: TemplateCreate):
    try:
        data = body.dict(exclude_none=True)
        result = await create_meta_template(body.clientId, data) 
        
        logger.info(f"Meta API Create Result: {result}")
        if isinstance(result, dict) and "error" in result:
            return {
                "success": False,
                "message": {"error": result["error"]}
            }
            
        if isinstance(result, dict) and "id" in result:
            tmpl_id = str(result["id"])
            async with AsyncSessionLocal() as session:
                try:
                    t_res = await session.execute(select(Template).where(Template.id == tmpl_id))
                    existing = t_res.scalars().first()
                    if not existing:
                        new_tmpl = Template(
                            id=tmpl_id,
                            client_id=body.clientId,
                            name=body.name,
                            category=body.category,
                            components=body.components,
                            status=result.get("status", "PENDING"),
                            language=body.language,
                            type=getattr(body, "type", None) or "Text",
                        )
                        session.add(new_tmpl)
                        await session.commit()
                except Exception as db_e:
                    logger.error(f"Error auto-saving template to DB: {db_e}")

        return {"success": True, "data": result}

    except Exception as e:
        logger.error(f"Error creating template: {e}")
        return {"success": False, "message": str(e)}

@router.post("/saveTemplate")
async def save_template_to_db(payload: Dict[str, Any] = Body(...)):
    """Save full template model (including carousel cards, userCategory, etc.) to PostgreSQL."""
    client_id = payload.get("clientId") or payload.get("client_id")
    template_id = payload.get("id") or payload.get("templateId")
    if not client_id or not template_id:
        return {"success": False, "message": "Missing clientId or template id"}

    async with AsyncSessionLocal() as session:
        try:
            t_res = await session.execute(select(Template).where(Template.id == str(template_id)))
            existing = t_res.scalars().first()
            if existing:
                existing.name = payload.get("name", existing.name)
                existing.category = payload.get("category", existing.category)
                existing.components = payload.get("components", existing.components)
                existing.status = payload.get("status", existing.status)
                existing.language = payload.get("language", existing.language)
                existing.type = payload.get("type", existing.type)
                existing.user_category = payload.get("userCategory", existing.user_category)
                existing.cards = payload.get("cards", existing.cards)
            else:
                new_tmpl = Template(
                    id=str(template_id),
                    client_id=client_id,
                    name=payload.get("name"),
                    category=payload.get("category"),
                    components=payload.get("components"),
                    status=payload.get("status", "PENDING"),
                    language=payload.get("language", "en"),
                    type=payload.get("type", "Text"),
                    user_category=payload.get("userCategory"),
                    cards=payload.get("cards"),
                )
                session.add(new_tmpl)
            await session.commit()
            return {"success": True, "message": "Template saved to database"}
        except Exception as e:
            logger.error(f"Error saving template to DB: {e}")
            return {"success": False, "message": str(e)}

@router.get("/getTemplateDetails")
async def get_template_details(
    clientId: str = Query(...),
    templateId: str = Query(None),
    name: str = Query(None)
):
    """Fetch template details from PostgreSQL database or Meta API fallback."""
    async with AsyncSessionLocal() as session:
        try:
            query = select(Template).where(Template.client_id == clientId)
            if templateId:
                query = query.where(Template.id == str(templateId))
            elif name:
                query = query.where(Template.name == name)
            else:
                return {"success": False, "message": "Missing templateId or name"}

            res = await session.execute(query)
            tmpl = res.scalars().first()
            if tmpl:
                return {
                    "success": True,
                    "data": {
                        "id": tmpl.id,
                        "name": tmpl.name,
                        "category": tmpl.category,
                        "userCategory": tmpl.user_category,
                        "language": tmpl.language,
                        "type": tmpl.type,
                        "status": tmpl.status,
                        "components": tmpl.components,
                        "cards": tmpl.cards,
                    }
                }
            
            # Fallback: fetch from Meta templates
            meta_res = await get_meta_templates(clientId)
            if isinstance(meta_res, dict) and "data" in meta_res:
                for t in meta_res["data"]:
                    if (templateId and str(t.get("id")) == str(templateId)) or (name and t.get("name") == name):
                        return {"success": True, "data": t}

            return {"success": False, "message": "Template not found"}
        except Exception as e:
            logger.error(f"Error fetching template details: {e}")
            return {"success": False, "message": str(e)}

@router.get("/getInteraktTemplates")
async def get_templates(
    clientId: str = Query(None),
    limit: int = Query(None),
    after: str = Query(None),
    before: str = Query(None),
    status: str = Query(None),
    category: str = Query(None),
    language: str = Query(None)
):
    try:
        if not clientId:
             return {"success": False, "message": "Missing clientId"}
             
        result = await get_meta_templates(
            clientId, 
            limit=limit, 
            after=after, 
            before=before,
            status=status,
            category=category,
            language=language
        )
        
        if isinstance(result, dict) and "error" in result:
             return {"success": False, "error": result["error"]}
             
        return {"success": True, "data": result}

    except Exception as e:
        logger.error(f"Error fetching templates: {e}")
        return {"success": False, "message": str(e)}


@router.get("/getApprovedTemplates")
async def get_approved(clientId: str = Query(...)):
    try:
        result = await get_meta_templates(clientId, status="APPROVED", fields="id,name,category,status,language,components")
        
        if isinstance(result, dict) and "error" in result:
             return {"success": False, "error": result["error"]}
             
        if isinstance(result, dict) and "data" in result and isinstance(result["data"], list):
             # Filter out Meta default sample template 'hello_world' which is restricted to test numbers
             result["data"] = [t for t in result["data"] if t.get("name") != "hello_world"]

        return {"success": True, "data": result}

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
    file: UploadFile = File(...),
    clientId: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
):
    try:
        cid = (clientId or client_id or "").strip()
        if not cid:
            return JSONResponse(status_code=400, content={"success": False, "message": "clientId is required"})
        secrets = await get_secrets(cid)
        if not secrets:
            logger.error(f"Client secrets not found for clientId: '{cid}'")
            return JSONResponse(status_code=404, content={"success": False, "message": f"Client secrets not found for client {cid}"})
        content = await file.read()
        content_type = file.content_type or "image/jpeg"
        filename = file.filename or "media.jpg"
        handle = await create_media_handle(secrets, content, filename, content_type)
        return {"success": True, "media_handle_id": handle}
    except Exception as e:
        logger.error(f"Error in uploadMediaToInterakt: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@router.post("/uploadMedia")
@router.post("/uploadBroadcastMedia")
async def upload_media_id_endpoint(
    file: UploadFile = File(...),
    clientId: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
):
    try:
        cid = (clientId or client_id or "").strip()
        if not cid:
            return JSONResponse(status_code=400, content={"success": False, "message": "clientId is required"})
        secrets = await get_secrets(cid)
        if not secrets:
            logger.error(f"Client secrets not found for clientId: '{cid}'")
            return JSONResponse(status_code=404, content={"success": False, "message": f"Client secrets not found for client {cid}"})
        content = await file.read()
        content_type = file.content_type or "image/jpeg"
        filename = file.filename or "media.jpg"
        mid = await create_media_id(secrets, content, filename, content_type)
        return {"success": True, "media_id": mid}
    except Exception as e:
        logger.error(f"Error in uploadBroadcastMedia: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})
