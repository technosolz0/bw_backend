from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AppStatusResponse(BaseModel):
    maintenance_mode: bool
    allow_log_store: bool

    class Config:
        from_attributes = True

class ToggleStatusRequest(BaseModel):
    status: bool

class LogCreateRequest(BaseModel):
    user_id: str
    device_info: str
    message: str

class LogResponse(BaseModel):
    success: bool
    message: Optional[str] = None
