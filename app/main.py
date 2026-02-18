from fastapi import FastAPI
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

from app.database import init_db
from fastapi.staticfiles import StaticFiles

@app.on_event("startup")
async def on_startup():
    await init_db()

# Mount static files for local media storage
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return {"message": "WhatsApp Business Backend is running (PostgreSQL)"}
