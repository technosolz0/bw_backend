from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.future import select
from dotenv import load_dotenv
import os
import logging
from app.routers import webhook, analytics, tools, chat, profile, templates, migration, scheduler
from control.routes import router as control_router
import control.models

# Load environment variables
load_dotenv()

# Logger setup
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Business WhatsApp Backend")

# Include Routers
app.include_router(webhook.router)
app.include_router(analytics.router)
app.include_router(tools.router)
app.include_router(chat.router)
app.include_router(profile.router)
app.include_router(templates.router)
app.include_router(migration.router)
app.include_router(scheduler.router)
app.include_router(control_router)

from app.database import init_db, AsyncSessionLocal
from control.models import AppConfig
from fastapi.staticfiles import StaticFiles

# Maintenance Middleware
@app.middleware("http")
async def check_maintenance_mode(request: Request, call_next):
    # Paths that are ALWAYS allowed (Admin and Status)
    exempt_paths = ["/admin", "/app-status", "/docs", "/openapi.json", "/static", "/"]
    
    if any(request.url.path.startswith(path) for path in exempt_paths):
        return await call_next(request)

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(AppConfig).limit(1))
            config = result.scalars().first()
            if config and config.maintenance_mode:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "System is under maintenance. Please try again later."}
                )
        except Exception as e:
            # If DB error, log it but let the request through to avoid locking out the app
            print(f"Middleware DB Error: {e}")

    return await call_next(request)

@app.on_event("startup")
async def on_startup():
    await init_db()

# Mount static files for local media storage
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return {"message": "WhatsApp Business Backend is running (PostgreSQL)"}
