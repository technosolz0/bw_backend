from app.database import AsyncSessionLocal
from app.models.sql_models import Client
from sqlalchemy.future import select
import os

async def get_secrets(client_id: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Client).where(Client.client_id == client_id))
        client = result.scalars().first()
        
        if not client:
            return None
            
        return {
            "wabaId": client.waba_id,
            "phoneNumberId": client.phone_number_id,
            "phoneNumber": client.phone_number,
            "webhookVerifyToken": client.webhook_verify_token,
            "storeId": client.store_id,
            "qnaStoreId": client.qna_store_id,
            "googleApiKey": client.google_api_key
        }

def get_base_url():
    # In JS it was process.env.BASE_URL. 
    # Since we are moving to Python, we should ensure this is set in .env
    # The original .env didn't show BASE_URL, but it was used in code. 
    # It might be the Facebook Graph API URL: https://graph.facebook.com/v21.0
    # Let's default to a likely value if not in env.
    return os.getenv("BASE_URL", "https://graph.facebook.com/v21.0")

def extract_phone_number(full_number: str):
    cleaned = "".join([c for c in full_number if c.isdigit()])
    
    country_codes = [
        {'code': '91', 'length': 2},
        {'code': '1', 'length': 1},
        {'code': '44', 'length': 2},
        {'code': '61', 'length': 2},
        {'code': '86', 'length': 2},
        {'code': '81', 'length': 2},
        {'code': '49', 'length': 2},
        {'code': '33', 'length': 2},
        {'code': '39', 'length': 2},
        {'code': '34', 'length': 2},
        {'code': '55', 'length': 2},
        {'code': '52', 'length': 2},
        {'code': '27', 'length': 2},
        {'code': '234', 'length': 3},
        {'code': '254', 'length': 3},
        {'code': '971', 'length': 3},
        {'code': '966', 'length': 3},
        {'code': '92', 'length': 2},
        {'code': '880', 'length': 3},
        {'code': '94', 'length': 2},
        {'code': '977', 'length': 3},
    ]

    for item in country_codes:
        code = item['code']
        length = item['length']
        if cleaned.startswith(code):
            phone_number = cleaned[length:]
            country_code = f"+{code}"
            return {"phoneNumber": phone_number, "countryCode": country_code}
            
    if len(cleaned) > 10:
        country_code_length = len(cleaned) - 10
        country_code = f"+{cleaned[:country_code_length]}"
        phone_number = cleaned[country_code_length:]
        return {"phoneNumber": phone_number, "countryCode": country_code}

    return {"phoneNumber": cleaned, "countryCode": "+91"}

