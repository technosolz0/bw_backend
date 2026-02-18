from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db

from .models import AppConfig, AppLog
from .schemas import AppStatusResponse, ToggleStatusRequest, LogCreateRequest, LogResponse
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

X_API_KEY = os.getenv("API_KEY", "SUPER@SECRET@KEY@32")

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != X_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials"
        )
    return x_api_key

async def get_config(db: AsyncSession):
    result = await db.execute(select(AppConfig).limit(1))
    config = result.scalars().first()
    if not config:
        # Initialize default config if it doesn't exist
        config = AppConfig(maintenance_mode=False, allow_log_store=True)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config

@router.get("/app-status", response_model=AppStatusResponse)
async def get_app_status(db: AsyncSession = Depends(get_db)):
    config = await get_config(db)
    return config

@router.post("/admin/toggle-maintenance", dependencies=[Depends(verify_api_key)])
async def toggle_maintenance(request: ToggleStatusRequest, db: AsyncSession = Depends(get_db)):
    config = await get_config(db)
    config.maintenance_mode = request.status
    await db.commit()
    return {"message": f"Maintenance mode set to {request.status}"}

@router.post("/admin/toggle-log-store", dependencies=[Depends(verify_api_key)])
async def toggle_log_store(request: ToggleStatusRequest, db: AsyncSession = Depends(get_db)):
    config = await get_config(db)
    config.allow_log_store = request.status
    await db.commit()
    return {"message": f"Log store allowed set to {request.status}"}

@router.post("/store-log", response_model=LogResponse, dependencies=[Depends(verify_api_key)])
async def store_log(log_data: LogCreateRequest, db: AsyncSession = Depends(get_db)):
    config = await get_config(db)
    
    if not config.allow_log_store:
        return {"success": False, "message": "Log storing is currently disabled"}
    
    new_log = AppLog(
        user_id=log_data.user_id,
        device_info=log_data.device_info,
        message=log_data.message
    )
    db.add(new_log)
    await db.commit()
    return {"success": True}
