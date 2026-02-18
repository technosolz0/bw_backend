from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from app.database import Base


class AppConfig(Base):
    __tablename__ = "app_configs"

    id = Column(Integer, primary_key=True, index=True)
    maintenance_mode = Column(Boolean, default=False)
    allow_log_store = Column(Boolean, default=True)

class AppLog(Base):
    __tablename__ = "app_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    device_info = Column(String)
    message = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
