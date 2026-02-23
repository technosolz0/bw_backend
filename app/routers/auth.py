from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import AsyncSessionLocal
from app.models.sql_models import Admin
from app.schemas import LoginRequest, LoginResponse
import jwt
import datetime
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/auth", tags=["auth"])

SECRET_KEY = "e74cdbd286112fae" # Matches Flutter's AppConstants.menuItemsSecret
ALGORITHM = "HS256"

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest = Body(...)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Admin).where(Admin.email == body.email)
        )
        admin = result.scalars().first()
        
        # Checking plain text password for alignment with Firestore legacy logic
        if not admin or admin.password != body.password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
            
        # Update last logged in
        admin.last_logged_in = datetime.datetime.now()
        await session.commit()
        
        # Prepare JWT payload
        payload = {
            'adminId': admin.id,
            'clientId': admin.client_id,
            'email': admin.email,
            'password': admin.password, # Including password in JWT as per Flutter code
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
        }
        
        token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        
        admin_data = {
            "id": admin.id,
            "client_id": admin.client_id,
            "email": admin.email,
            "first_name": admin.first_name,
            "last_name": admin.last_name,
            "profile_photo": admin.profile_photo,
            "is_super_user": admin.is_super_user,
            "is_all_chats": admin.is_all_chats,
            "assigned_pages": admin.assigned_pages or []
        }
        
        return {
            "success": True,
            "token": token,
            "admin": admin_data,
            "clientId": admin.client_id
        }
