from fastapi import APIRouter, Request, Response, HTTPException
from app.services.analytics import (
    get_time_range_params,
    fetch_conversation_analytics,
    fetch_messages_analytics,
    process_analytics_data
)
from app.services.utils import get_secrets
import logging
import asyncio

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/getConversationAnalytics")
async def get_conversation_analytics(request: Request):
    try:
        query_params = request.query_params
        client_id = query_params.get("clientId")
        filter_str = query_params.get("filter", "This Month")
        custom_start = query_params.get("customStart")
        custom_end = query_params.get("customEnd")
        
        if not client_id:
             return Response("clientId is required", status_code=400)
             
        secrets = await get_secrets(client_id)
        if not secrets:
             return Response("Secrets not found", status_code=404)
        
        time_params = get_time_range_params(filter_str, custom_start, custom_end)
        start = time_params["start"]
        end = time_params["end"]
        granularity = time_params["granularity"]
        
        logger.info(f"Fetching analytics for {filter_str} start={start} end={end} granularity={granularity}")
        
        # Parallel fetch
        conversation_data, messages_data = await asyncio.gather(
            fetch_conversation_analytics(secrets, start, end, granularity),
            fetch_messages_analytics(secrets, start, end, granularity)
        )
        
        metrics = process_analytics_data(conversation_data, messages_data)
        
        return {
            "success": True,
            "filter": filter_str,
            "dateRange": {
                "start": datetime.datetime.fromtimestamp(start).isoformat(),
                "end": datetime.datetime.fromtimestamp(end).isoformat(),
                "granularity": granularity
            },
            "metrics": metrics,
            "rawData": {
                "conversations": conversation_data,
                "messages": messages_data
            }
        }

    except Exception as e:
        logger.error(f"Error fetching analytics: {e}")
        return {
            "success": False,
            "error": str(e)
        }
import datetime
