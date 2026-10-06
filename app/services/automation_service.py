import logging
import asyncio
from typing import Dict, Any, Optional, List
from firebase_admin import firestore
from app.services.firebase_service import db
from app.services.chat import send_whatsapp_message_helper

logger = logging.getLogger(__name__)

async def execute_automation(
    client_id: str,
    contact_id: str,
    phone_number: str,
    message_text: str,
    message_type: str = "text"
) -> bool:
    """
    Evaluates incoming WhatsApp message against active automations and sessions.
    Returns True if an automation handled the message, False otherwise.
    """
    if not db:
        logger.debug("Firestore not initialized, skipping automation execution.")
        return False

    if not client_id or not contact_id or not phone_number:
        return False

    cleaned_text = (message_text or "").strip()

    try:
        session_ref = (
            db.collection("automation_sessions")
            .document(client_id)
            .collection("data")
            .document(contact_id)
        )
        session_doc = session_ref.get()
        session_data = session_doc.to_dict() if session_doc.exists else None

        # 1. Check if user is currently in an active session
        if session_data and session_data.get("active", False):
            handled = await continue_automation_session(
                client_id=client_id,
                contact_id=contact_id,
                phone_number=phone_number,
                session_ref=session_ref,
                session_data=session_data,
                user_input=cleaned_text,
                message_type=message_type
            )
            return handled

        # 2. Check if incoming message triggers a new automation
        if message_type == "text" and cleaned_text:
            text_lower = cleaned_text.lower()
            
            # Query active automations for this client
            automations_ref = (
                db.collection("automations")
                .document(client_id)
                .collection("data")
            )
            
            # Query where status == 'Active'
            active_docs = automations_ref.where("status", "==", "Active").stream()
            
            for doc in active_docs:
                flow = doc.to_dict() or {}
                trigger_keywords = flow.get("trigger_keywords", []) or []
                
                # Check keyword match (exact or contained)
                matched = False
                for kw in trigger_keywords:
                    kw_clean = str(kw).strip().lower()
                    if kw_clean and (kw_clean == text_lower or kw_clean in text_lower.split()):
                        matched = True
                        break

                if matched:
                    logger.info(f"🎯 Automation triggered: '{flow.get('flowName')}' (ID: {flow.get('id', doc.id)}) for contact {contact_id}")
                    await start_automation_flow(
                        client_id=client_id,
                        contact_id=contact_id,
                        phone_number=phone_number,
                        session_ref=session_ref,
                        flow=flow,
                        flow_id=flow.get("id", doc.id),
                        user_input=cleaned_text
                    )
                    return True

        return False

    except Exception as e:
        logger.error(f"Error in execute_automation: {e}", exc_info=True)
        return False


async def start_automation_flow(
    client_id: str,
    contact_id: str,
    phone_number: str,
    session_ref: Any,
    flow: Dict[str, Any],
    flow_id: str,
    user_input: str
):
    """Initializes a new session and begins node traversal."""
    start_node_id = flow.get("start_node")
    if not start_node_id:
        logger.warning(f"Automation {flow_id} has no start_node configured.")
        return

    session_data = {
        "automation_id": flow_id,
        "current_node": start_node_id,
        "active": True,
        "variables": {"initial_input": user_input},
        "updatedAt": firestore.SERVER_TIMESTAMP,
        "createdAt": firestore.SERVER_TIMESTAMP,
    }
    session_ref.set(session_data, merge=True)

    await traverse_nodes(
        client_id=client_id,
        contact_id=contact_id,
        phone_number=phone_number,
        session_ref=session_ref,
        flow=flow,
        current_node_id=start_node_id,
        user_input=user_input,
        visited=[]
    )


async def continue_automation_session(
    client_id: str,
    contact_id: str,
    phone_number: str,
    session_ref: Any,
    session_data: Dict[str, Any],
    user_input: str,
    message_type: str
) -> bool:
    """Resumes an active automation session based on user input."""
    flow_id = session_data.get("automation_id")
    current_node_id = session_data.get("current_node")

    if not flow_id or not current_node_id:
        session_ref.update({"active": False})
        return False

    # Check for cancellation / stop keywords
    if user_input.lower() in ["stop", "cancel", "exit", "quit", "end"]:
        logger.info(f"User requested to stop automation {flow_id}")
        session_ref.update({
            "active": False,
            "stopped_by_user": True,
            "updatedAt": firestore.SERVER_TIMESTAMP
        })
        await send_whatsapp_message_helper({
            "clientId": client_id,
            "phoneNumber": phone_number,
            "message": "Automation stopped. How else may we help you?",
            "chatId": contact_id,
            "messageType": "text"
        })
        return True

    # Fetch flow definition
    flow_doc = (
        db.collection("automations")
        .document(client_id)
        .collection("data")
        .document(flow_id)
        .get()
    )

    if not flow_doc.exists:
        logger.warning(f"Automation flow {flow_id} not found in Firestore.")
        session_ref.update({"active": False})
        return False

    flow = flow_doc.to_dict() or {}
    nodes = flow.get("nodes", {}) or {}
    current_node = nodes.get(current_node_id)

    if not current_node:
        logger.warning(f"Node {current_node_id} not found in flow {flow_id}.")
        session_ref.update({"active": False})
        return False

    next_node_id = None
    node_type = current_node.get("type", "")

    # Handle Question / Menu response
    if node_type in ["menu", "question"]:
        options = current_node.get("options", {}) or {}
        user_input_lower = user_input.lower().strip()

        # Match option key or label
        for opt_label, target_id in options.items():
            opt_label_lower = str(opt_label).lower().strip()
            if user_input_lower == opt_label_lower or user_input_lower in opt_label_lower:
                next_node_id = target_id
                break

        # Fallback to direct next_node if options didn't match or were empty
        if not next_node_id:
            next_node_id = current_node.get("next_node")

    # Handle Condition node directly following user response
    elif node_type == "condition":
        next_node_id = evaluate_condition(current_node, user_input)

    else:
        # Standard continuation to next_node
        next_node_id = current_node.get("next_node")

    if next_node_id:
        await traverse_nodes(
            client_id=client_id,
            contact_id=contact_id,
            phone_number=phone_number,
            session_ref=session_ref,
            flow=flow,
            current_node_id=next_node_id,
            user_input=user_input,
            visited=[]
        )
        return True
    else:
        # No further nodes, finish session
        session_ref.update({"active": False, "updatedAt": firestore.SERVER_TIMESTAMP})
        return True


def evaluate_condition(node_data: Dict[str, Any], user_input: str) -> Optional[str]:
    """Evaluates condition criteria and returns target node ID for 'true' or 'false'."""
    condition_val = str(node_data.get("condition_value") or node_data.get("content") or "").lower().strip()
    operator = str(node_data.get("operator") or "contains").lower().strip()
    input_val = str(user_input or "").lower().strip()

    is_true = False
    if operator == "equals":
        is_true = (input_val == condition_val)
    elif operator == "starts_with":
        is_true = input_val.startswith(condition_val)
    elif operator == "ends_with":
        is_true = input_val.endswith(condition_val)
    elif operator == "regex":
        import re
        try:
            is_true = bool(re.search(condition_val, input_val))
        except Exception:
            is_true = False
    else:  # default 'contains'
        is_true = condition_val in input_val

    true_node = node_data.get("true_node")
    false_node = node_data.get("false_node")

    chosen_node = true_node if is_true else false_node
    logger.info(f"Condition '{condition_val}' {operator} '{input_val}' => {is_true}. Moving to node: {chosen_node}")
    return chosen_node


async def traverse_nodes(
    client_id: str,
    contact_id: str,
    phone_number: str,
    session_ref: Any,
    flow: Dict[str, Any],
    current_node_id: str,
    user_input: str,
    visited: List[str]
):
    """Recursively traverses and executes flow nodes."""
    nodes = flow.get("nodes", {}) or {}

    while current_node_id:
        if current_node_id in visited:
            logger.error(f"Cycle detected in automation traversal at node {current_node_id}")
            session_ref.update({"active": False})
            break

        visited.append(current_node_id)
        current_node = nodes.get(current_node_id)

        if not current_node:
            logger.warning(f"Node {current_node_id} does not exist in flow.")
            session_ref.update({"active": False})
            break

        node_type = current_node.get("type", "message")
        content = current_node.get("content", "")

        # 1. MESSAGE / TEXT_FIELD
        if node_type in ["message", "text_field"]:
            if content:
                await send_whatsapp_message_helper({
                    "clientId": client_id,
                    "phoneNumber": phone_number,
                    "message": content,
                    "chatId": contact_id,
                    "messageType": "text"
                })
                # Small pause to guarantee message delivery ordering
                await asyncio.sleep(0.3)

            current_node_id = current_node.get("next_node")
            session_ref.update({
                "current_node": current_node_id or "",
                "updatedAt": firestore.SERVER_TIMESTAMP
            })

        # 2. CONDITION
        elif node_type == "condition":
            next_target = evaluate_condition(current_node, user_input)
            current_node_id = next_target
            session_ref.update({
                "current_node": current_node_id or "",
                "updatedAt": firestore.SERVER_TIMESTAMP
            })

        # 3. ACTION
        elif node_type == "action":
            action_type = current_node.get("action_type") or "assign_dept"
            action_value = current_node.get("action_value") or content

            logger.info(f"⚡ Executing action '{action_type}' with value '{action_value}' for contact {contact_id}")
            
            # Action logic: e.g., if there's custom message or assignment
            if content and content != action_value:
                await send_whatsapp_message_helper({
                    "clientId": client_id,
                    "phoneNumber": phone_number,
                    "message": content,
                    "chatId": contact_id,
                    "messageType": "text"
                })

            current_node_id = current_node.get("next_node")
            session_ref.update({
                "current_node": current_node_id or "",
                "updatedAt": firestore.SERVER_TIMESTAMP
            })

        # 4. QUESTION / MENU (Waits for user input)
        elif node_type in ["menu", "question"]:
            menu_text = content or "Please make a selection:"
            options = current_node.get("options", {}) or {}

            # Append formatted numbered options if available
            if options and not any(str(k).isdigit() for k in options.keys() if len(str(k)) <= 2):
                menu_lines = [menu_text]
                for idx, opt_label in enumerate(options.keys(), start=1):
                    menu_lines.append(f"{idx}. {opt_label}")
                menu_text = "\n".join(menu_lines)

            await send_whatsapp_message_helper({
                "clientId": client_id,
                "phoneNumber": phone_number,
                "message": menu_text,
                "chatId": contact_id,
                "messageType": "text"
            })

            # Halt traversal: wait for user's next message
            session_ref.update({
                "current_node": current_node_id,
                "state": "waiting_for_input",
                "active": True,
                "updatedAt": firestore.SERVER_TIMESTAMP
            })
            logger.info(f"Automation paused at Question/Menu node {current_node_id}, waiting for response.")
            break

        # 5. STOP
        elif node_type == "stop":
            logger.info(f"Automation reached Stop node {current_node_id}. Closing session.")
            session_ref.update({
                "current_node": current_node_id,
                "active": False,
                "updatedAt": firestore.SERVER_TIMESTAMP
            })
            break

        else:
            logger.warning(f"Unknown node type: {node_type} at {current_node_id}")
            current_node_id = current_node.get("next_node")
            session_ref.update({
                "current_node": current_node_id or "",
                "updatedAt": firestore.SERVER_TIMESTAMP
            })

    # If reached the end of flow
    if not current_node_id:
        session_ref.update({"active": False, "updatedAt": firestore.SERVER_TIMESTAMP})
