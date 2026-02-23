from fastapi import APIRouter, Query, HTTPException, status, Body
from sqlalchemy.future import select
from app.database import AsyncSessionLocal
from app.models.sql_models import Role, Admin
from app.schemas import RoleCreate, RoleUpdate, Role as RoleSchema
import logging
import datetime
from typing import List

router = APIRouter(prefix="/roles", tags=["roles"])
logger = logging.getLogger(__name__)

@router.get("/getRoles")
async def get_roles(clientId: str = Query(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Role).where(Role.client_id == clientId).order_by(Role.created_at)
            )
            roles = result.scalars().all()
            return {"success": True, "data": roles}
        except Exception as e:
            logger.error(f"Error fetching roles: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/addRole")
async def add_role(role_data: RoleCreate):
    async with AsyncSessionLocal() as session:
        try:
            new_role = Role(**role_data.dict())
            if not new_role.id:
                new_role.id = str(int(datetime.datetime.now().timestamp() * 1000))
            
            session.add(new_role)
            await session.commit()
            return {"success": True, "roleId": new_role.id}
        except Exception as e:
            logger.error(f"Error adding role: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/updateRole")
async def update_role(roleId: str = Query(...), role_data: RoleUpdate = Body(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Role).where(Role.id == roleId)
            )
            role = result.scalars().first()
            if not role:
                raise HTTPException(status_code=404, detail="Role not found")
            
            old_role_name = role.role_name
            
            for key, value in role_data.dict(exclude_none=True).items():
                setattr(role, key, value)
            
            role.updated_at = datetime.datetime.now()
            
            # If role name changed, update all admins with this role
            if role_data.role_name and role_data.role_name != old_role_name:
                admin_result = await session.execute(
                    select(Admin).where(Admin.role == old_role_name, Admin.client_id == role.client_id)
                )
                admins = admin_result.scalars().all()
                for admin in admins:
                    admin.role = role_data.role_name
                    admin.assigned_pages = role_data.assigned_pages or role.assigned_pages # redundant but aligns with Flutter logic
            
            # Even if name didn't change, update permissions for admins with this role
            # This matches Flutter logic in AddRolesController
            else:
                admin_result = await session.execute(
                    select(Admin).where(Admin.role == role.role_name, Admin.client_id == role.client_id)
                )
                admins = admin_result.scalars().all()
                for admin in admins:
                    admin.assigned_pages = role.assigned_pages

            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating role: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.delete("/deleteRole")
async def delete_role(roleId: str = Query(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Role).where(Role.id == roleId)
            )
            role = result.scalars().first()
            if not role:
                raise HTTPException(status_code=404, detail="Role not found")
            
            role_name = role.role_name
            client_id = role.client_id
            
            # Remove role from admins
            admin_result = await session.execute(
                select(Admin).where(Admin.role == role_name, Admin.client_id == client_id)
            )
            admins = admin_result.scalars().all()
            for admin in admins:
                admin.role = None
                admin.assigned_pages = []
            
            await session.delete(role)
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting role: {e}")
            raise HTTPException(status_code=500, detail=str(e))
