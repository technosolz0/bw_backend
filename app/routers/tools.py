from fastapi import APIRouter, Request, Response
import phonenumbers
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/getPhoneNumber")
async def get_phone_number(request: Request):
    phone_param = request.query_params.get("phoneNumber")
    if not phone_param:
        return Response(content='{"error": "Missing phoneNumber query parameter"}', status_code=400, media_type="application/json")
        
    try:
        phone_number = None
        error_to_throw = None
        
        # 1. Try international
        try:
            intl_param = phone_param if phone_param.startswith("+") else f"+{phone_param}"
            parsed = phonenumbers.parse(intl_param, None)
            if phonenumbers.is_valid_number(parsed):
                phone_number = parsed
        except Exception as e:
            error_to_throw = e
            
        # 2. Try default region IN
        if not phone_number and not phone_param.startswith("+"):
            try:
                local_parsed = phonenumbers.parse(phone_param, "IN")
                if phonenumbers.is_valid_number(local_parsed):
                    phone_number = local_parsed
            except Exception as e:
                if not error_to_throw:
                    error_to_throw = e
                    
        if not phone_number:
            raise error_to_throw or Exception("Invalid phone number")
            
        return {
            "countryCallingCode": phone_number.country_code,
            "nationalNumber": phone_number.national_number,
            "number": f"+{phone_number.country_code}{phone_number.national_number}",
            "country": phonenumbers.region_code_for_number(phone_number)
        }
        
    except Exception as e:
        logger.error(f"Error parsing phone number: {e}")
        return Response(content=f'{{"error": "Invalid phone number format", "details": "{str(e)}"}}', status_code=400, media_type="application/json")
