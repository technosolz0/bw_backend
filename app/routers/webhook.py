from fastapi import APIRouter, Request, Response, HTTPException, Query, Body
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


@router.get("/webhook")
async def verify_webhook(
    challenge: str = Query(None, alias="hub.challenge"),
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token")
):
    logger.info(f"VERIFY_WEBHOOK: mode={mode}, token={token}, challenge={challenge}")
    
    # Meta sends these 3 parameters. If token matches what we set in Meta Dashboard, 
    # we MUST return the challenge.
    
    # Get verify token from env, default to "bw.backend" as seen in logs
    verify_token = os.getenv("WEBHOOK_VERIFY_TOKEN", "bw.backend")
    
    if mode == "subscribe" and token == verify_token:
        logger.info("Webhook verified successfully!")
        return PlainTextResponse(content=challenge)
        
    # If it's just a test request with a challenge but no token/mode validation needed
    if challenge and not mode:
        return PlainTextResponse(content=challenge)
        
    logger.warning(f"Webhook verification failed. Expected token: {verify_token}")
    return Response(status_code=400, content="Verification failed")

from app.schemas import MetaWebhookPayload

@router.post("/webhook")
async def webhook_event(request: Request, body: MetaWebhookPayload = Body(None)):
    # MetaWebhookPayload enables Swagger documentation.
    # We still allow Body(None) and use request.body() for internal fallback or raw logging if needed.
    
    # Get raw body first to check if empty
    raw_body = await request.body()
    
    # Handle empty body (common for webhook testing)
    if not raw_body or raw_body == b'':
        logger.info("Received empty webhook POST request - likely a test")
        return Response(status_code=200, content="Webhook endpoint is active")
    
    # Try to use body object if provided and valid, else parse raw_body
    if body:
        body = body.dict()
    else:
        try:
            body = await request.json()
        except Exception as e:
            logger.error(f"Failed to parse webhook JSON: {e}. Raw body: {raw_body[:500]}")
            return Response(status_code=400, content=f"Invalid JSON: {str(e)}")

    # Check if this is a proper Meta webhook format
    if not isinstance(body, dict):
        logger.error(f"Invalid webhook body: not a dict, got {type(body)}")
        await log_webhook(None, "invalid_payload", {"error": "Body is not a JSON object", "type": str(type(body))}, "ERROR")
        return Response(status_code=200)

    logger.info(f"Webhook event received: {body.get('object')}")

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
                client_id = phone_number_id
                logger.info(f"Processing webhook for Client ID (PhoneNumberID): {client_id}, Field: {field}")
                
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


@router.post("/handleInboundMessage")
async def handle_inbound_message(request: Request):
    """
    Handles inbound messages from PubSub or direct webhook calls, mirroring Google Cloud Function handleInboundMessage.
    Accepts:
    1. Google Cloud PubSub push payloads: { "message": { "data": "base64..." } }
    2. Direct JSON payloads: { "message": { ... }, "clientId": "...", "chatId": "..." }
    3. Asynchronous node processing: { "clientId": "...", "from": "...", "chatId": "...", "automationId": "...", "nodeId": "..." }
    """
    try:
        import base64
        import json
        from app.services.automation_service import (
            execute_automation,
            get_automation_flow,
            traverse_nodes
        )
        from app.services.firebase_service import db

        raw_body = await request.body()
        if not raw_body:
            return Response(status_code=200, content="Empty body")

        body = await request.json()

        # Handle PubSub push envelope
        if isinstance(body, dict) and "message" in body and isinstance(body["message"], dict) and "data" in body["message"]:
            try:
                data_b64 = body["message"]["data"]
                decoded_str = base64.b64decode(data_b64).decode("utf-8")
                body = json.loads(decoded_str)
            except Exception as pe:
                logger.error(f"Failed to decode PubSub message data: {pe}")
                return Response(status_code=200, content="Invalid PubSub payload")

        # 1. Asynchronous node traversal step
        if body.get("nodeId") and body.get("automationId"):
            client_id = body.get("clientId")
            from_phone = body.get("from")
            chat_id = body.get("chatId")
            automation_id = body.get("automationId")
            node_id = body.get("nodeId")
            visited = body.get("visited", [])

            flow = await get_automation_flow(client_id, automation_id)
            if flow:
                session_ref = None
                if db:
                    session_ref = (
                        db.collection("automation_sessions")
                        .document(client_id)
                        .collection("data")
                        .document(chat_id)
                    )
                await traverse_nodes(
                    client_id=client_id,
                    contact_id=chat_id,
                    phone_number=from_phone,
                    session_ref=session_ref,
                    flow=flow,
                    current_node_id=node_id,
                    user_input="",
                    visited=visited
                )
            return Response(status_code=200, content="Node processed")

        # 2. Standard inbound message handling
        msg = body.get("message", {})
        client_id = body.get("clientId")
        chat_id = body.get("chatId")

        from_phone = msg.get("from") or body.get("from")
        msg_type = msg.get("type", "text")
        text_body = ""
        if msg_type == "text":
            text_body = msg.get("text", {}).get("body", "") or body.get("text", "")

        logger.info(f"handleInboundMessage received: client_id={client_id}, chat_id={chat_id}, from={from_phone}")

        handled = await execute_automation(
            client_id=client_id,
            contact_id=chat_id,
            phone_number=from_phone,
            message_text=text_body,
            message_type=msg_type
        )

        return Response(status_code=200, content=json.dumps({"success": True, "handled": handled}), media_type="application/json")

    except Exception as e:
        logger.error(f"Error in handleInboundMessage endpoint: {e}", exc_info=True)
        return Response(status_code=200, content=f"Error: {e}")

