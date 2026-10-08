from fastapi import APIRouter, HTTPException, Query, Body
from typing import Dict, Any, Optional, List
import logging
import datetime
import json
from sqlalchemy.future import select
from app.database import AsyncSessionLocal
from app.models.sql_models import Automation
from app.services.automation_service import execute_automation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/automations", tags=["Automations"])

@router.get("")
async def list_automations(client_id: str = Query(..., description="Client ID")):
    """List all automations for a given client from PostgreSQL database."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Automation)
                .where(Automation.client_id == client_id)
                .order_by(Automation.created_at.desc())
            )
            rows = result.scalars().all()
            automations = []
            for a in rows:
                automations.append({
                    "id": a.id,
                    "flowName": a.flow_name,
                    "name": a.flow_name,
                    "status": a.status,
                    "ui_flow": a.ui_flow,
                    "nodes": a.nodes,
                    "trigger_keywords": a.trigger_keywords or [],
                    "triggerKeywords": a.trigger_keywords or [],
                    "start_node": a.start_node,
                    "startNode": a.start_node,
                    "createdBy": a.created_by,
                    "createdAt": a.created_at.isoformat() if a.created_at else None,
                    "updatedAt": a.updated_at.isoformat() if a.updated_at else None,
                })
            return {"success": True, "data": automations, "total": len(automations)}
        except Exception as e:
            logger.error(f"Error listing automations: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/{automation_id}")
async def get_automation(automation_id: str, client_id: str = Query(..., description="Client ID")):
    """Get a single automation flow from PostgreSQL."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Automation).where(
                    Automation.id == automation_id,
                    Automation.client_id == client_id
                )
            )
            a = result.scalars().first()
            if not a:
                raise HTTPException(status_code=404, detail="Automation not found")
            data = {
                "id": a.id,
                "flowName": a.flow_name,
                "name": a.flow_name,
                "status": a.status,
                "ui_flow": a.ui_flow,
                "nodes": a.nodes,
                "trigger_keywords": a.trigger_keywords or [],
                "triggerKeywords": a.trigger_keywords or [],
                "start_node": a.start_node,
                "startNode": a.start_node,
                "createdBy": a.created_by,
                "createdAt": a.created_at.isoformat() if a.created_at else None,
                "updatedAt": a.updated_at.isoformat() if a.updated_at else None,
            }
            return {"success": True, "data": data}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting automation: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

@router.post("")
async def save_automation(payload: Dict[str, Any] = Body(...)):
    """Create or update an automation flow in PostgreSQL."""
    client_id = payload.get("clientId") or payload.get("client_id")
    flow_id = payload.get("id")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")

    try:
        import time
        doc_id = str(flow_id) if flow_id else str(int(time.time() * 1000))
        flow_name = payload.get("flowName") or payload.get("name") or "Untitled Flow"
        status = payload.get("status") or "Active"
        
        ui_flow = payload.get("ui_flow")
        if isinstance(ui_flow, (dict, list)):
            ui_flow = json.dumps(ui_flow)
        elif ui_flow is not None:
            ui_flow = str(ui_flow)
            
        nodes = payload.get("nodes") or {}
        trigger_keywords = payload.get("triggerKeywords") or payload.get("trigger_keywords") or []
        start_node = payload.get("startNode") or payload.get("start_node")
        created_by = payload.get("createdBy") or payload.get("created_by") or ""

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Automation).where(Automation.id == doc_id)
            )
            existing = result.scalars().first()
            if existing:
                existing.client_id = client_id
                existing.flow_name = flow_name
                existing.status = status
                existing.ui_flow = ui_flow
                existing.nodes = nodes
                existing.trigger_keywords = trigger_keywords
                existing.start_node = start_node
                existing.updated_at = datetime.datetime.now(datetime.timezone.utc)
            else:
                new_auto = Automation(
                    id=doc_id,
                    client_id=client_id,
                    flow_name=flow_name,
                    status=status,
                    ui_flow=ui_flow,
                    nodes=nodes,
                    trigger_keywords=trigger_keywords,
                    start_node=start_node,
                    created_by=created_by,
                )
                session.add(new_auto)
            await session.commit()

        return {"success": True, "id": doc_id, "message": "Automation saved successfully"}
    except Exception as e:
        logger.error(f"Error saving automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{automation_id}")
async def delete_automation(automation_id: str, client_id: str = Query(...)):
    """Delete an automation flow from PostgreSQL."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Automation).where(
                    Automation.id == automation_id,
                    Automation.client_id == client_id
                )
            )
            existing = result.scalars().first()
            if existing:
                await session.delete(existing)
                await session.commit()
            return {"success": True, "message": "Automation deleted successfully"}
        except Exception as e:
            logger.error(f"Error deleting automation: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/{automation_id}/toggle")
async def toggle_automation_status(
    automation_id: str,
    client_id: str = Query(...),
    status: Optional[str] = Body(None)
):
    """Toggle automation status between Active and Inactive in PostgreSQL."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Automation).where(
                    Automation.id == automation_id,
                    Automation.client_id == client_id
                )
            )
            existing = result.scalars().first()
            if not existing:
                raise HTTPException(status_code=404, detail="Automation not found")

            current_status = existing.status or "Active"
            new_status = status if status else ("Inactive" if current_status == "Active" else "Active")

            existing.status = new_status
            existing.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()
            return {"success": True, "status": new_status}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error toggling automation status: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-trigger")
async def test_trigger(payload: Dict[str, Any] = Body(...)):
    """Manually test triggering an automation with simulated user input."""
    client_id = payload.get("clientId") or payload.get("client_id")
    contact_id = payload.get("contactId") or payload.get("contact_id") or "test_contact"
    phone_number = payload.get("phoneNumber") or payload.get("phone_number") or "919999999999"
    message_text = payload.get("messageText") or payload.get("message_text") or "hello"

    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")

    handled = await execute_automation(
        client_id=client_id,
        contact_id=contact_id,
        phone_number=phone_number,
        message_text=message_text,
        message_type="text"
    )
    return {"success": True, "handled": handled}
