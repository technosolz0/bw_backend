from fastapi import APIRouter, Request, Response
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

from fastapi import Body

@router.post("/migrateCollectionData")
async def migrate_collection_data(clientId: str = Body(..., embed=True)):
    return {"success": False, "message": "Firebase Migration tool is deprecated in PostgreSQL version."}
