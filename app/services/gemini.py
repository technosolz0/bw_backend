from google import genai
from google.genai import types
from app.database import AsyncSessionLocal
from app.models.sql_models import Message, Contact, UnansweredQuestion
from sqlalchemy.future import select
from datetime import timezone, timedelta
import datetime
import logging
import os

logger = logging.getLogger(__name__)

# Default system instruction if none provided in config
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant for a business managing WhatsApp communications."

def get_ist_time():
    return datetime.datetime.now(timezone(timedelta(hours=5, minutes=30)))

async def get_chat_history(client_id, session_id, limit=10):
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Message).where(
                    Message.client_id == client_id,
                    Message.chat_id == session_id,
                    Message.message_type == 'text'
                ).order_by(Message.timestamp.desc()).limit(limit)
            )
            messages = result.scalars().all()
            
            history = []
            for msg in messages:
                history.append(types.Content(
                    role="model" if msg.is_from_me else "user",
                    parts=[types.Part.from_text(text=msg.content or "")]
                ))
        
        return history[::-1]
    except Exception as e:
        logger.error(f"Error fetching history for chat session {session_id}: {e}")
        return []

async def generate_content_with_file_search(client_id, prompt, api_key, store_ids, model_name="gemini-2.0-flash-lite", config=None, session_id=None, context_window=10):
    if not api_key:
        raise ValueError("googleApiKey is not set in client's secrets.")
    
    client = genai.Client(api_key=api_key)
    
    # Use system_instruction from config or default
    system_instruction = config.get("system_instruction") if config else DEFAULT_SYSTEM_PROMPT

    tools = [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="scheduleCall",
                    description="Schedule a call with a business representative when a user provides a date and time.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "dateTime": types.Schema(
                                type="STRING",
                                description="The date and time the user wants to schedule the call for (e.g., 'tomorrow at 3pm', '2025-12-25 10:00')."
                            ),
                            "reason": types.Schema(
                                type="STRING",
                                description="The reason for the call or any specific topic mentioned by the user."
                            )
                        },
                        required=["dateTime"]
                    )
                )
            ]
        )
    ]

    history = []
    if session_id:
        history = await get_chat_history(client_id, session_id, context_window)
        
    logger.info(f"Generating content... sessionId: {session_id}, prompt: {prompt}")
    
    generate_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
    )

    try:
        chat = client.chats.create(model=model_name, config=generate_config, history=history)
        response = chat.send_message(prompt)
        
        response_text = response.text
        
        # Check for function calls
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                call = getattr(part, 'call', None)
                if call and call.name == "scheduleCall":
                    args = call.args
                    date_time = args.get("dateTime")
                    reason = args.get("reason")
                    logger.info(f"Tool Call: scheduleCall detected. DateTime: {date_time}, Reason: {reason}")
                    
                    await notify_sales_team(client_id, session_id, date_time, reason)
                    
                    if not response_text:
                        response_text = f"Great! I've noted down your request for a call on {date_time}. Our team will get back to you shortly."

        if response_text and "Would you like to schedule a call with a representative?" in response_text:
            await log_unanswered_question(client_id, session_id, prompt)

        return response_text
    except Exception as e:
        logger.error(f"Error generating content: {e}")
        return "I'm sorry, I'm having trouble processing your request right now."

async def notify_sales_team(client_id, contact_id, date_time, reason):
    try:
        sales_phone = os.getenv("SALES_TEAM_WHATSAPP")
        if not sales_phone:
            logger.warning("SALES_TEAM_WHATSAPP not set in .env")
            return
            
        contact_info = contact_id
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Contact).where(
                Contact.client_id == client_id,
                Contact.id == contact_id
            ))
            contact = result.scalars().first()
            if contact:
                f_name = contact.f_name or ""
                l_name = contact.l_name or ""
                phone = contact.phone_number or contact_id
                contact_info = f"{f_name} {l_name} ({phone})".strip()
            
        notification_text = f"🚀 *New Call Scheduled!*\n\n*Contact:* {contact_info}\n*Time:* {date_time}\n*Topic:* {reason or 'Not specified'}\n\nPlease reach out to the customer at the scheduled time."
        
        # TODO: Send notification via WhatsApp Interakt API
        logger.info(f"Sales team notified about call for contact {contact_id}")
            
    except Exception as e:
        logger.error(f"Error notifying sales team: {e}")

async def log_unanswered_question(client_id, contact_id, question):
    try:
        async with AsyncSessionLocal() as session:
            uq = UnansweredQuestion(
                client_id=client_id,
                contact_id=contact_id,
                question=question,
                timestamp=get_ist_time()
            )
            session.add(uq)
            await session.commit()
            
        logger.info(f"Unanswered question logged for contact {contact_id}")
    except Exception as e:
        logger.error(f"Error logging unanswered question: {e}")
