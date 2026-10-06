from fastapi import APIRouter, HTTPException, Query, Body
from typing import Dict, Any, Optional, List
import logging
from firebase_admin import firestore
from app.services.firebase_service import db
from app.services.automation_service import execute_automation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/automations", tags=["Automations"])

@router.get("")
async def list_automations(client_id: str = Query(..., description="Client ID")):
    """List all automations for a given client from Firestore."""
    if not db:
        raise HTTPException(status_code=500, detail="Firestore not initialized")

    try:
        docs = (
            db.collection("automations")
            .document(client_id)
            .collection("data")
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .stream()
        )
        automations = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = data.get("id") or doc.id
            automations.append(data)
        return {"success": True, "data": automations, "total": len(automations)}
    except Exception as e:
        logger.error(f"Error listing automations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{automation_id}")
async def get_automation(automation_id: str, client_id: str = Query(..., description="Client ID")):
    """Get a single automation flow."""
    if not db:
        raise HTTPException(status_code=500, detail="Firestore not initialized")

    try:
        doc = (
            db.collection("automations")
            .document(client_id)
            .collection("data")
            .document(automation_id)
            .get()
        )
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Automation not found")
        data = doc.to_dict()
        data["id"] = data.get("id") or doc.id
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
async def save_automation(payload: Dict[str, Any] = Body(...)):
    """Create or update an automation flow."""
    if not db:
        raise HTTPException(status_code=500, detail="Firestore not initialized")

    client_id = payload.get("clientId") or payload.get("client_id")
    flow_id = payload.get("id")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")

    try:
        import time
        doc_id = str(flow_id) if flow_id else str(int(time.time() * 1000))
        payload["id"] = doc_id
        payload["updatedAt"] = firestore.SERVER_TIMESTAMP
        if not flow_id:
            payload["createdAt"] = firestore.SERVER_TIMESTAMP

        doc_ref = (
            db.collection("automations")
            .document(client_id)
            .collection("data")
            .document(doc_id)
        )
        doc_ref.set(payload, merge=True)
        return {"success": True, "id": doc_id, "message": "Automation saved successfully"}
    except Exception as e:
        logger.error(f"Error saving automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{automation_id}")
async def delete_automation(automation_id: str, client_id: str = Query(...)):
    """Delete an automation flow."""
    if not db:
        raise HTTPException(status_code=500, detail="Firestore not initialized")

    try:
        db.collection("automations").document(client_id).collection("data").document(automation_id).delete()
        return {"success": True, "message": "Automation deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{automation_id}/toggle")
async def toggle_automation_status(automation_id: str, client_id: str = Query(...), status: Optional[str] = Body(None)):
    """Toggle automation status between Active and Inactive."""
    if not db:
        raise HTTPException(status_code=500, detail="Firestore not initialized")

    try:
        doc_ref = db.collection("automations").document(client_id).collection("data").document(automation_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Automation not found")

        current_status = doc.to_dict().get("status", "Active")
        new_status = status if status else ("Inactive" if current_status == "Active" else "Active")

        doc_ref.update({"status": new_status, "updatedAt": firestore.SERVER_TIMESTAMP})
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
