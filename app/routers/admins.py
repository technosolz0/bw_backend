from fastapi import APIRouter, Query, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import AsyncSessionLocal
from app.models.sql_models import Admin
from app.schemas import AdminCreate, AdminUpdate, Admin as AdminSchema
import logging
import datetime

router = APIRouter(prefix="/admins", tags=["admins"])
logger = logging.getLogger(__name__)

@router.get("/getAdmins")
async def get_admins(clientId: str = Query(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Admin).where(Admin.client_id == clientId).order_by(Admin.created_at)
            )
            admins = result.scalars().all()
            return {"success": True, "data": admins}
        except Exception as e:
            logger.error(f"Error fetching admins: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/getAdminById")
async def get_admin_by_id(adminId: str = Query(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Admin).where(Admin.id == adminId)
            )
            admin = result.scalars().first()
            if not admin:
                raise HTTPException(status_code=404, detail="Admin not found")
            return {"success": True, "data": admin}
        except Exception as e:
            logger.error(f"Error fetching admin: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/addAdmin")
async def add_admin(admin_data: AdminCreate):
    async with AsyncSessionLocal() as session:
        try:
            # Check for duplicate email
            result = await session.execute(
                select(Admin).where(Admin.email == admin_data.email)
            )
            if result.scalars().first():
                raise HTTPException(status_code=400, detail="Email already exists")
                
            new_admin = Admin(**admin_data.dict())
            session.add(new_admin)
            await session.commit()
            return {"success": True, "adminId": new_admin.id}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/updateAdmin")
async def update_admin(adminId: str = Query(...), admin_data: AdminUpdate = Body(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Admin).where(Admin.id == adminId)
            )
            admin = result.scalars().first()
            if not admin:
                raise HTTPException(status_code=404, detail="Admin not found")
            
            for key, value in admin_data.dict(exclude_none=True).items():
                setattr(admin, key, value)
            
            admin.updated_at = datetime.datetime.now()
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating admin: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.patch("/patchAdmin")
async def patch_admin(adminId: str = Query(...), admin_data: AdminUpdate = Body(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Admin).where(Admin.id == adminId)
            )
            admin = result.scalars().first()
            if not admin:
                raise HTTPException(status_code=404, detail="Admin not found")
            
            for key, value in admin_data.dict(exclude_none=True).items():
                setattr(admin, key, value)
            
            admin.updated_at = datetime.datetime.now()
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error patching admin: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.delete("/deleteAdmin")
async def delete_admin(adminId: str = Query(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Admin).where(Admin.id == adminId)
            )
            admin = result.scalars().first()
            if not admin:
                raise HTTPException(status_code=404, detail="Admin not found")
            
            # Here you might want to move it to a deleted_admins table as in Flutter logic
            # For now, let's just delete
            await session.delete(admin)
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting admin: {e}")
            raise HTTPException(status_code=500, detail=str(e))
