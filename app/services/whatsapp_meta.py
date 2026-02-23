from app.services.utils import get_secrets, get_base_url
import httpx
import os
import logging
# from app.services.firebase import db

logger = logging.getLogger(__name__)

async def get_meta_token():
    # Prefer META_TOKEN, fallback to INTERAKT_TOKEN
    return os.getenv("META_TOKEN") or os.getenv("INTERAKT_TOKEN")

async def get_app_id(access_token):
    # Fetch App ID using debug_token
    try:
        url = "https://graph.facebook.com/v21.0/debug_token"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params={
                "input_token": access_token,
                "access_token": access_token
            })
            data = resp.json()
            return data.get("data", {}).get("app_id")
    except Exception as e:
        logger.error(f"Error fetching App ID: {e}")
        return None

async def create_media_handle(secrets, file_content, file_name, mime_type):
    # Implements Resumable Upload API to get a handle
    try:
        base_url = get_base_url()
        token = await get_meta_token()
        app_id = await get_app_id(token)
        
        if not app_id:
            raise ValueError("Could not determine App ID for Resumable Upload")

        # 1. Initiate Upload
        init_url = f"{base_url}/{app_id}/uploads"
        file_length = len(file_content)
        
        async with httpx.AsyncClient() as client:
            # Step 1: Initialize
            init_resp = await client.post(
                init_url,
                params={
                    "file_length": file_length,
                    "file_type": mime_type
                },
                headers={"Authorization": f"Bearer {token}"}
            )
            init_resp.raise_for_status()
            session_id = init_resp.json().get("id")
            
            # Step 2: Upload Content
            upload_url = f"{base_url}/{session_id}"
            
            # Headers for upload
            headers = {
                "Authorization": f"Bearer {token}",
                "file_offset": "0"
            }
            
            upload_resp = await client.post(
                upload_url,
                content=file_content,
                headers=headers,
                timeout=60.0
            )
            upload_resp.raise_for_status()
            
            # The handle is in the 'h' field of the response
            return upload_resp.json().get("h")
            
    except Exception as e:
        logger.error(f"Error in createMediaHandle: {e}")
        if hasattr(e, 'response') and e.response:
             logger.error(f"Response: {e.response.text}")
        raise e

async def create_media_id(secrets, file_content, file_name, mime_type):
    try:
        base_url = get_base_url()
        token = await get_meta_token()
        
        url = f"{base_url}/{secrets['phoneNumberId']}/media"
        
        files = {
            "file": (file_name, file_content, mime_type)
        }
        data = {
             "messaging_product": "whatsapp",
             "type": mime_type
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                files=files,
                data=data,
                headers={
                    "Authorization": f"Bearer {token}"
                },
                timeout=60.0
            )
            response.raise_for_status()
            return response.json().get("id")
            
    except Exception as e:
        logger.error(f"Error in createMediaId: {e}")
        raise e

async def get_whatsapp_business_profile(client_id):
    secrets = await get_secrets(client_id)
    if not secrets:
        raise ValueError("Secrets not found")
        
    base_url = get_base_url()
    token = await get_meta_token()
    
    url = f"{base_url}/{secrets['phoneNumberId']}/whatsapp_business_profile"
    params = {
        "fields": "about,address,description,email,profile_picture_url,websites,vertical"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        )
        data = response.json()
        return data.get("data", [{}])[0]

async def update_whatsapp_business_profile(client_id, payload):
    secrets = await get_secrets(client_id)
    if not secrets:
        raise ValueError("Secrets not found")
        
    base_url = get_base_url()
    token = await get_meta_token()
    
    url = f"{base_url}/{secrets['phoneNumberId']}/whatsapp_business_profile"
    
    payload["messaging_product"] = "whatsapp"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
             headers={
                "Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"
            }
        )
        return response.json()

async def create_meta_template(client_id, template_data):
    secrets = await get_secrets(client_id)
    base_url = get_base_url()
    token = await get_meta_token()
    
    # Construct payload logic based on template_data
    # This logic matches createMetaTemplate in templateHandler.js
    
    name = template_data.get("name")
    language = template_data.get("language")
    category = template_data.get("category")
    template_type = template_data.get("templateType", "Text")
    
    components = []
    
    # Header
    header = template_data.get("header")
    media_handle_id = template_data.get("media_handle_id")
    media_type = template_data.get("mediaType")
    
    if media_handle_id:
        components.append({
            "type": "HEADER",
            "format": media_type.upper(),
            "example": {"header_handle": [media_handle_id]}
        })
    elif header and header.strip():
        components.append({
            "type": "HEADER",
            "format": "TEXT",
            "text": header,
            "example": {"header_text": [header]}
        })
        
    # Body
    body = template_data.get("body")
    body_examples = template_data.get("bodyExampleValues", [])
    body_comp = {"type": "BODY", "text": body}
    if body_examples:
        body_comp["example"] = {"body_text": [body_examples]}
    components.append(body_comp)
    
    # Footer
    footer = template_data.get("footer")
    if footer and footer.strip():
        components.append({"type": "FOOTER", "text": footer})
        
    # Buttons
    buttons = template_data.get("buttons", [])
    if buttons:
        processed_buttons = []
        for b in buttons:
            mapped = {"type": b["type"], "text": b["text"]}
            if b["type"] == "URL":
                mapped["url"] = b["url"]
                if b.get("example"):
                    mapped["example"] = b["example"][0]
            elif b["type"] == "PHONE_NUMBER":
                mapped["phone_number"] = b["phone_number"]
            elif b["type"] == "COPY_CODE":
                 if b.get("example"):
                    mapped["example"] = b["example"][0]
            processed_buttons.append(mapped)
        
        components.append({"type": "BUTTONS", "buttons": processed_buttons})
        
    final_payload = {
        "name": name,
        "language": language,
        "category": category.upper(),
        "components": components
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/{secrets['wabaId']}/message_templates",
            json=final_payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        )
        return response.json()

async def get_meta_templates(client_id, limit=None, after=None, before=None, status=None, fields=None):
    secrets = await get_secrets(client_id)
    base_url = get_base_url()
    token = await get_meta_token()
    
    params = {}
    if limit: params["limit"] = limit
    if after: params["after"] = after
    if before: params["before"] = before
    if status: params["status"] = status
    if fields: params["fields"] = fields
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{base_url}/{secrets['wabaId']}/message_templates",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        )
        return response.json()

async def delete_meta_template(client_id, name):
    secrets = await get_secrets(client_id)
    base_url = get_base_url()
    token = await get_meta_token()
    
    import urllib.parse
    encoded_name = urllib.parse.quote(name)
    
    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f"{base_url}/{secrets['wabaId']}/message_templates?name={encoded_name}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        )
        return response.json()

async def send_template_message(
    client_id: str,
    secrets: dict,
    template_name: str,
    language: str,
    body_vars: list = None,
    media_id: str = None,
    phone_number: str = None,
    header_text: str = None,
    media_type: str = "image",
    button_payloads: list = None
):
    """
    Sends a WhatsApp template message using the Meta Cloud API.
    Supports text, media (image, video, document), and interactive components (buttons).
    """
    try:
        base_url = get_base_url()
        token = await get_meta_token()
        
        # Determine the components
        components = []
        
        # 1. Header Component
        header_params = []
        if media_id:
            m_type = media_type.lower()
            header_params.append({
                "type": m_type,
                m_type: {
                    "id": media_id
                }
            })
            # For documents, header_text might be used as the filename
            if m_type == "document" and header_text:
                 header_params[0][m_type]["filename"] = header_text
        elif header_text:
            header_params.append({
                "type": "text",
                "text": header_text
            })
            
        if header_params:
            components.append({
                "type": "header",
                "parameters": header_params
            })
            
        # 2. Body Component
        if body_vars:
            body_params = []
            for val in body_vars:
                body_params.append({
                    "type": "text",
                    "text": str(val)
                })
            components.append({
                "type": "body",
                "parameters": body_params
            })
            
        # 3. Button Components (Quick Replies)
        if button_payloads:
            for index, payload in enumerate(button_payloads):
                if payload:
                    components.append({
                        "type": "button",
                        "sub_type": "quick_reply",
                        "index": str(index),
                        "parameters": [{
                            "type": "payload",
                            "payload": payload
                        }]
                    })
                    
        # Construct Final Payload
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language
                }
            }
        }
        
        if components:
            payload["template"]["components"] = components
            
        url = f"{base_url}/{secrets['phoneNumberId']}/messages"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            return response.json()
            
    except Exception as e:
        logger.error(f"Error in send_template_message: {e}")
        if hasattr(e, 'response') and e.response:
             logger.error(f"Response: {e.response.text}")
        raise e
