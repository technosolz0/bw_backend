from app.services.utils import get_secrets, get_base_url
import httpx
import os
import datetime
import logging

logger = logging.getLogger(__name__)

async def fetch_conversation_analytics(secrets, start, end, granularity):
    try:
        conversation_granularity = "DAILY" if granularity == "DAY" else "MONTHLY"
        base_url = get_base_url()
        waba_id = secrets.get("wabaId")
        phone_number = secrets.get("phoneNumber")
        token = os.getenv("META_TOKEN") or os.getenv("INTERAKT_TOKEN")
        
        analytics_url = f"{base_url}/{waba_id}"
        params = {
            "fields": f"conversation_analytics.start({start}).end({end}).granularity({conversation_granularity}).phone_numbers([{phone_number}]).metric_types(['COST','CONVERSATION']).conversation_categories(['MARKETING','SERVICE','UTILITY']).conversation_types(['FREE_ENTRY_POINT','FREE_TIER','REGULAR','UNKNOWN']).conversation_directions(['BUSINESS_INITIATED','UNKNOWN']).dimensions(['CONVERSATION_TYPE','CONVERSATION_DIRECTION','CONVERSATION_CATEGORY'])"
        }
        
        full_url = f"{analytics_url}?{params['fields']}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                full_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
            # response.raise_for_status() 
            data = response.json()
            return data.get("conversation_analytics", {}).get("data", [{}])[0].get("data_points", [])

    except Exception as e:
        logger.error(f"Error fetching conversation analytics: {e}")
        return []

async def fetch_messages_analytics(secrets, start, end, granularity):
    try:
        messages_granularity = granularity
        base_url = get_base_url()
        waba_id = secrets.get("wabaId")
        phone_number = secrets.get("phoneNumber")
        token = os.getenv("META_TOKEN") or os.getenv("INTERAKT_TOKEN")

        analytics_url = f"{base_url}/{waba_id}"
        fields = f"analytics.start({start}).end({end}).granularity({messages_granularity}).phone_numbers([{phone_number}]).product_types([0,2])"
        full_url = f"{analytics_url}?fields={fields}"
        
        logger.info(f"Using Messages Analytics URL: {full_url}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                full_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
            data = response.json()
            return data.get("analytics", {}).get("data_points", [])
            
    except Exception as e:
        logger.error(f"Error fetching messages analytics: {e}")
        return []

def get_time_range_params(filter_str, custom_start=None, custom_end=None):
    now = datetime.datetime.now()
    start = None
    end = None
    granularity = "DAY"
    
    if filter_str == "Today":
        start = datetime.datetime(now.year, now.month, now.day)
        end = now
        granularity = "DAY"
        
    elif filter_str == "This Month":
        start = datetime.datetime(now.year, now.month, 1)
        end = now
        granularity = "DAY"
        
    elif filter_str == "Last Month":
        # First day of prev month
        last_month = now.replace(day=1) - datetime.timedelta(days=1)
        start = last_month.replace(day=1)
        # Last day of prev month
        end = last_month.replace(hour=23, minute=59, second=59) 
        # Actually end param works better if it covers the range.
        # JS: new Date(now.getFullYear(), now.getMonth(), 0) -> last day of prev month
        granularity = "DAY"
        
    elif filter_str == "Last 6 Months":
        start = now - datetime.timedelta(days=6*30) # approx
        end = now
        granularity = "MONTH"
        
    elif filter_str == "Custom Date Range":
        if not custom_start or not custom_end:
            raise ValueError("Custom date range requires customStart and customEnd")
        start = datetime.datetime.fromtimestamp(int(custom_start))
        end = datetime.datetime.fromtimestamp(int(custom_end))
        
        days_diff = (end - start).days
        granularity = "DAY" if days_diff <= 31 else "MONTH"
    
    else:
        # Default This Month
        start = datetime.datetime(now.year, now.month, 1)
        end = now
        granularity = "DAY"

    return {
        "start": int(start.timestamp()),
        "end": int(end.timestamp()),
        "granularity": granularity
    }

def process_analytics_data(conversation_data, messages_data):
    free_messages = 0
    paid_messages = 0
    total_cost = 0.0
    
    total_sent = 0
    total_delivered = 0
    
    delivered_by_category = {"marketing": 0, "utility": 0, "service": 0, "unknown": 0}
    free_messages_by_type = {"customerService": 0, "entryPoint": 0}
    paid_by_category = {"marketing": 0, "utility": 0, "service": 0, "unknown": 0}
    cost_by_category = {"marketing": 0.0, "utility": 0.0, "service": 0.0, "unknown": 0.0}
    
    for point in conversation_data:
        conversation = point.get("conversation", 0)
        conv_type = point.get("conversation_type")
        direction = point.get("conversation_direction")
        category = (point.get("conversation_category") or "unknown").lower()
        cost = point.get("cost", 0)
        
        if direction not in ["UNKNOWN", "BUSINESS_INITIATED"]:
            continue
            
        if category in delivered_by_category:
            delivered_by_category[category] += conversation
        else:
            delivered_by_category["unknown"] += conversation
            
        if conv_type in ["FREE_ENTRY_POINT", "FREE_TIER"]:
            free_messages += conversation
            if conv_type == "FREE_ENTRY_POINT":
                free_messages_by_type["entryPoint"] += conversation
            else:
                free_messages_by_type["customerService"] += conversation
                
        if conv_type in ["REGULAR", "UNKNOWN"]:
            paid_messages += conversation
            if category in paid_by_category:
                paid_by_category[category] += conversation
        
        total_cost += cost
        if category in cost_by_category:
            cost_by_category[category] += cost

    for point in messages_data:
        total_sent += point.get("sent", 0)
        total_delivered += point.get("delivered", 0)
        
    total_delivered_conversations = sum(delivered_by_category.values())
    
    return {
        "allMessages": {
            "total": total_sent,
            "breakdown": [
                {"label": "Sent", "value": total_sent},
                {"label": "Delivered", "value": total_delivered}
            ]
        },
        "messagesDelivered": {
            "total": total_delivered_conversations,
            "breakdown": [
                {"label": "Marketing", "value": delivered_by_category["marketing"]},
                {"label": "Utility", "value": delivered_by_category["utility"]},
                {"label": "Service", "value": delivered_by_category["service"]},
            ]
        },
        "freeMessages": {
            "total": free_messages,
            "breakdown": [
                {"label": "Customer Service", "value": free_messages_by_type["customerService"]},
                {"label": "Entry Point", "value": free_messages_by_type["entryPoint"]},
            ]
        },
        "paidMessages": {
            "total": paid_messages,
            "breakdown": [
                {"label": "Marketing", "value": paid_by_category["marketing"]},
                {"label": "Utility", "value": paid_by_category["utility"]},
                {"label": "Service", "value": paid_by_category["service"]},
            ]
        },
        "totalCharges": {
            "total": f"{total_cost:.2f}",
            "currency": "₹",
            "breakdown": [
                {"label": "Marketing", "value": f"{cost_by_category['marketing']:.2f}"},
                {"label": "Utility", "value": f"{cost_by_category['utility']:.2f}"},
                {"label": "Service", "value": f"{cost_by_category['service']:.2f}"},
            ]
        }
    }
