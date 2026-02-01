from fastapi import APIRouter, Request, Response
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/migrateCollectionData")
async def migrate_collection_data(request: Request):
    return {"success": False, "message": "Firebase Migration tool is deprecated in PostgreSQL version."}
