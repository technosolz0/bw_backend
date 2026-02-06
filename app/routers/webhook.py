from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import PlainTextResponse
from app.services.webhook_handlers import (
    log_webhook,
    handle_status_update,
    handle_category_update,
    handle_chat_message,
    handle_message_status_update,
    update_user_preference
)
import logging
import os

router = APIRouter()
logger = logging.getLogger(__name__)

from fastapi import Query

@router.get("/webhook")
async def verify_webhook(
    challenge: str = Query(None, alias="hub.challenge"),
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token")
):
    # Replicating JS logic: strictly check challenge existence.
    # Checks on token are commented out in original JS, but we can verify against env if we want.
    # verify_token = os.getenv("WEBHOOK_VERIFY_TOKEN", "my_secure_chat_webhook_2024")
    
    if challenge:
        # if mode == "subscribe" and token == verify_token:
        return PlainTextResponse(content=challenge)
        
    return Response(status_code=400)

@router.post("/webhook")
async def webhook_event(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        return Response(status_code=400)

    # Check if this is a proper Meta webhook format
    # Meta format: { "object": "whatsapp_business_account", "entry": [...] }
    if not isinstance(body, dict):
        logger.error(f"Invalid webhook body: not a dict, got {type(body)}")
        await log_webhook(None, "invalid_payload", {"error": "Body is not a JSON object", "type": str(type(body))}, "ERROR")
        return Response(status_code=200)

    # Check for Meta webhook format
    if body.get("object") != "whatsapp_business_account":
        # Not a Meta webhook - could be a test payload or different format
        logger.warning(f"Unexpected webhook format - missing 'object': {list(body.keys())}")
        # Still try to process if it has entry, otherwise log and return 200
        if not body.get("entry"):
            logger.error(f"Invalid webhook body: missing 'entry' array. Keys: {list(body.keys())}")
            await log_webhook(None, "invalid_payload", {"error": "Missing 'entry' array", "received_keys": list(body.keys()), "sample": str(body)[:500]}, "ERROR")
            return Response(status_code=200)
    
    if not isinstance(body.get("entry"), list):
        logger.error(f"Invalid webhook body: 'entry' is not an array, got {type(body.get('entry'))}")
        await log_webhook(None, "invalid_payload", {"error": "'entry' is not an array", "entry_type": str(type(body.get("entry")))}, "ERROR")
        return Response(status_code=200)

    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                field = change.get("field")
                value = change.get("value", {})
                
                # metadata could be in value.metadata or value directly?
                # JS: const phoneNumberId = value.metadata?.phone_number_id;
                phone_number_id = value.get("metadata", {}).get("phone_number_id")
                
                # Note: We use phoneNumberId as clientId in many places in JS logs, 
                # but handlers take 'clientId'.
                # In the JS handlers (e.g. handleStatusUpdate(clientId, value)), 
                # usually clientId is passed.
                # Is phoneNumberId == clientId?
                # In helper functions, existing code queried collections using 'clientId'.
                # We need to ensure we use the correct ID.
                # In standard WhatsApp Cloud API, phoneNumberId is effectively the client ID if configured that way.
                # Let's check how 'logWebhook' was called in JS: logWebhook(phoneNumberId, ...)
                
                client_id = phone_number_id
                
                if field == "message_template_status_update":
                    await log_webhook(client_id, "status_update", value)
                    await handle_status_update(client_id, value)
                    
                elif field == "template_category_update":
                    await log_webhook(client_id, "category_update", value)
                    await handle_category_update(client_id, value)
                    
                elif field == "messages":
                    if value.get("statuses"):
                        # await log_webhook(client_id, "message_status_update", value)
                        await handle_message_status_update(client_id, value)
                    else:
                        # await log_webhook(client_id, "chat_message", value)
                        await handle_chat_message(client_id, value)
                        
                elif field == "user_preferences":
                    await log_webhook(client_id, "user_preference", value)
                    await update_user_preference(client_id, value)
                    
                else:
                    await log_webhook(client_id, "unknown_event", {"field": field, "value": value})

        return Response(status_code=200)

    except Exception as e:
        logger.error(f"WEBHOOK ERROR: {e}")
        return Response(status_code=200) # Always return 200 to Meta to avoid retries on logic error
