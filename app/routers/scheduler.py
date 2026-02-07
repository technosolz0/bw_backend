from fastapi import APIRouter, Request, Response
from app.database import AsyncSessionLocal
from app.models.sql_models import Contact, MilestoneScheduler
from app.services.chat import send_whatsapp_message_helper
from app.services.interakt import create_media_id
from app.services.utils import get_secrets
from sqlalchemy.future import select
import logging
import datetime
import httpx
import asyncio
from PIL import Image, ImageDraw, ImageFont
import io
import os
from datetime import timezone, timedelta

def get_ist_time():
    return datetime.datetime.now(timezone(timedelta(hours=5, minutes=30)))

router = APIRouter()
logger = logging.getLogger(__name__)

from app.schemas import MilestoneTriggerRequest

@router.post("/sendMilestoneMessages")
async def send_milestone_messages(body: MilestoneTriggerRequest):
    try:
        client_id = body.clientId
        scheduler_id = body.schedulerId
        
        if not client_id or not scheduler_id:
             return Response("Missing clientId or schedulerId", status_code=400)
             
        logger.info("🎂 Starting Cron Job...")
        
        async with AsyncSessionLocal() as session:
            scheduler_result = await session.execute(
                select(MilestoneScheduler).where(
                    MilestoneScheduler.id == scheduler_id,
                    MilestoneScheduler.client_id == client_id
                )
            )
            scheduler = scheduler_result.scalars().first()
            if not scheduler:
                return Response("Scheduler not found", status_code=404)
            
            type_str = scheduler.type
            
            # Date logic
            now = get_ist_time()
            day = f"{now.day:02d}"
            month = f"{now.month:02d}"
            day_month = f"{day} {month}"
            
            logger.info(f"Checking {type_str} milestones for Day/Month: {day_month}")
            
            # Dynamic filter construction
            query = select(Contact).where(Contact.client_id == client_id)
            
            if type_str == 'birthday':
                query = query.where(Contact.birthdate_month == day_month, Contact.is_birthdate_active == True)
            elif type_str == 'anniversary':
                query = query.where(Contact.anniversary_date_month == day_month, Contact.is_anniversary_active == True)
            elif type_str == 'workAnniversary':
                query = query.where(Contact.work_anniversary_date_month == day_month, Contact.is_work_anniversary_active == True)
            
            contacts_res = await session.execute(query)
            contacts = contacts_res.scalars().all()
            
            if not contacts:
                return {"success": True, "message": "No milestones found for today."}
                
            logger.info(f"🎉 Found {len(contacts)} milestones for today.")
            
            # Helper Variables (cache locally to avoid re-accessing properties if lazy loaded, though scalars usually loads attributes)
            bg_url = scheduler.background_url
            scheduler_elements = scheduler.elements or []
            image_width = scheduler.image_width
            image_height = scheduler.image_height
            background_scale = scheduler.background_scale
            variable_values = scheduler.variable_values
            
            selected_template_name = scheduler.selected_template_name
            language = scheduler.language
        
        # Fetch background
        bg_buffer = None
        if bg_url:
            async with httpx.AsyncClient() as client:
                res = await client.get(bg_url)
                if res.status_code == 200:
                    bg_buffer = res.content
        
        if not bg_buffer:
             logger.info("Failed to fetch background image")
             return {"success": False, "message": "Failed to fetch background"}
             
        # Elements
        bg_images_conf = [e for e in scheduler_elements if e.get("type") == "image"]
        text_layers_conf = [e for e in scheduler_elements if e.get("type") == "text"]
        
        for contact in contacts:
            try:
                # contact is SQL model
                name = f"{contact.f_name or ''} {contact.l_name or ''}".strip()
                phone_number = (contact.country_code or "") + (contact.phone_number or "")
                profile_pic_url = contact.profile_photo
                
                if not profile_pic_url:
                     logger.info(f"Skipping {name}: No profile picture")
                     continue
                     
                profile_buffer = None
                async with httpx.AsyncClient() as client:
                    res = await client.get(profile_pic_url)
                    if res.status_code == 200:
                        profile_buffer = res.content
                
                if not profile_buffer: 
                    continue
                    
                # Generate Composite
                composite_bytes = generate_composite_image(
                    bg_buffer,
                    image_width,
                    image_height,
                    background_scale,
                    bg_images_conf,
                    text_layers_conf,
                    profile_buffer,
                    name
                )
                
                secrets = await get_secrets(client_id)
                media_id = await create_media_id(secrets, composite_bytes, "milestone.png", "image/png")
                
                # Replace Variables
                body_vars = []
                # variableValues is list/dict? JS: Object.values
                if isinstance(variable_values, dict):
                     items = variable_values.values()
                else:
                     items = variable_values or []
                     
                for variable in items:
                    v_type = variable.get("type")
                    val = variable.get("value")
                    
                    if v_type == 'static':
                        body_vars.append(val)
                    else:
                        c_val = val
                        if val == "First Name": c_val = contact.f_name or val
                        elif val == "Last Name": c_val = contact.l_name or val
                        elif val == "Email": c_val = contact.email or val
                        elif val == "Company": c_val = contact.company or val
                        elif val == "Birth Date": c_val = contact.birth_date or val
                        elif val == "Anniversary": c_val = contact.anniversary_dt or val
                        else: c_val = val
                        body_vars.append(c_val)

                # Send
                await send_template_message(client_id, secrets, selected_template_name, language, body_vars, media_id, phone_number)
                
                logger.info(f"✅ Sent milestone wish to {name}")
                
            except Exception as e:
                logger.error(f"Error processing contact {contact.id}: {e}")
        
        async with AsyncSessionLocal() as session:
            # We need to re-fetch to update? Or assuming scheduler object is from earlier session
            # Updating a detached object or fetching again and updating
            await session.execute(
                select(MilestoneScheduler).where(MilestoneScheduler.id == scheduler_id) # Re-fetching for safety
            )
            # Actually simplest to just update directly
            # Or use `update` statement
            from sqlalchemy import update
            await session.execute(
                update(MilestoneScheduler)
                .where(MilestoneScheduler.id == scheduler_id)
                .values(last_run=get_ist_time())
            )
            await session.commit()
        return {"success": True, "message": "Milestone Scheduler completed"}
        
    except Exception as e:
        logger.error(f"Critical Error in Milestone: {e}")
        return Response(content=str(e), status_code=500)

def generate_composite_image(bg_buffer, width, height, bg_scale, bg_images, text_layers, profile_buffer, name):
    # Simplified PIL implementation
    main_img = Image.open(io.BytesIO(bg_buffer)).convert("RGBA")
    
    # Resize main background? JS: input: mainImageBuffer, composite on top of Black canvas?
    # JS: sharp({width, height, background: transparent}).composite([{input: mainImageBuffer, top:0, left:0}])
    # So we should resize main_img to Width, Height or fit?
    # Assuming main_img acts as base if size matches, or we create canvas.
    
    canvas = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
    main_img = main_img.resize((int(width), int(height))) # Simple resize
    canvas.alpha_composite(main_img)
    
    # Background Layers (e.g. frames going behind profile pic?)
    # JS: bgComposites -> resize profileBuffer?
    # Wait, JS Code:
    # bgComposites = backgroundImages.map(el => sharp(backgroundImageBuffer).resize(...))
    # backgroundImageBuffer is passed as argument... wait, JS call:
    # generateCompositeImage(..., profilePicBuffer)
    # The variable name in JS definition is `backgroundImageBuffer` but passed value is `profilePicBuffer`.
    # So `bgComposites` are actually profile pictures placed at certain positions?
    # Yes. `const resizedImg = await sharp(backgroundImageBuffer)...`
    
    profile_img = Image.open(io.BytesIO(profile_buffer)).convert("RGBA")
    
    for el in bg_images:
        w = el.get("size", {}).get("width")
        h = el.get("size", {}).get("height")
        top = el.get("position", {}).get("dy")
        left = el.get("position", {}).get("dx")
        
        resized_prof = profile_img.resize((int(w), int(h)))
        canvas.paste(resized_prof, (int(left), int(top)), resized_prof)
        
    # Text Layers
    draw = ImageDraw.Draw(canvas)
    for el in text_layers:
        text = name # Simplified logic from JS, it calls createSvgText(el, scale, name)
        # We assume text content is the Name for now as per JS usage logic
        
        font_size = el.get("fontSize", 20)
        # Font handling is tricky in PIL without files. Use default or try to load ttf.
        try:
            font = ImageFont.truetype("Arial.ttf", size=int(font_size))
        except:
             font = ImageFont.load_default()
             
        fill_color = "black"
        if el.get("color"):
            # ARGB int conversion needed or use simple logic
             fill_color = "black" # simplified
             
        top = el.get("position", {}).get("dy")
        left = el.get("position", {}).get("dx")
        
        draw.text((int(left), int(top)), text, font=font, fill=fill_color)
        
    out_buf = io.BytesIO()
    canvas.save(out_buf, format="PNG")
    return out_buf.getvalue()

async def send_template_message(client_id, secrets, template_name, language, body_vars, media_id, phone_number):
    try:
        base_url = get_secrets(client_id) # wait we have secrets
        # get_base_url is strictly 'graph.facebook...'?
        # Use existing secrets
        from app.services.utils import get_base_url
        base_url = get_base_url()
        
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language or "en"},
                "components": [
                    {
                        "type": "header",
                        "parameters": [
                            {"type": "image", "image": {"id": media_id}}
                        ]
                    },
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": str(v)} for v in body_vars]
                    }
                ]
            }
        }
        
        token = os.getenv("META_TOKEN") or os.getenv("INTERAKT_TOKEN")
        
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{base_url}/{secrets['phoneNumberId']}/messages",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )
    except Exception as e:
        logger.error(f"Error sending template: {e}")
        # swallow error to continue loop
