from fastapi import APIRouter, Query, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import AsyncSessionLocal
from app.models.sql_models import Client, Charge, Wallet
from app.schemas import ResponseModel, ClientCreate, ClientUpdate
import logging
import datetime

router = APIRouter(prefix="/clients", tags=["clients"])
logger = logging.getLogger(__name__)

@router.get("/getClientDetails")
async def get_client_details(clientId: str = Query(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Client).where(Client.client_id == clientId)
            )
            client = result.scalars().first()
            
            if not client:
                return {
                    "name": None,
                    "logoUrl": "",
                    "isCRMEnabled": False,
                    "adminLimit": 0
                }
                
            return {
                "name": client.name,
                "logoUrl": client.logo_url or "",
                "isCRMEnabled": client.is_crm_enabled,
                "adminLimit": getattr(client, 'admin_limit', 0),
                "isPremium": getattr(client, 'is_premium', False),
                "subscriptionExpiry": client.subscription_expiry.isoformat() if client.subscription_expiry else None,
                "status": client.status
            }
        except Exception as e:
            logger.error(f"Error fetching client details: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/getCharges")
async def get_charges():
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(Charge))
            charges = result.scalars().all()
            
            charges_data = {}
            for charge in charges:
                charges_data[charge.id] = {
                    "name": charge.name,
                    "price": charge.price,
                    "description": charge.description
                }
            return charges_data
        except Exception as e:
            logger.error(f"Error fetching charges: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/get_all_clients")
async def get_all_clients():
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Client).order_by(Client.created_at.desc())
            )
            clients = result.scalars().all()
            return {"success": True, "data": clients}
        except Exception as e:
            logger.error(f"Error fetching all clients: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/addClient")
async def add_client(client_data: ClientCreate):
    async with AsyncSessionLocal() as session:
        try:
            # Check if client already exists
            existing_client = await session.execute(
                select(Client).where(Client.client_id == client_data.phone_number_id)
            )
            if existing_client.scalars().first():
                raise HTTPException(status_code=400, detail="Client with this ID already exists")

            new_client = Client(
                client_id=client_data.phone_number_id,
                name=client_data.name,
                phone_number=client_data.phone_number,
                phone_number_id=client_data.phone_number_id,
                waba_id=client_data.waba_id,
                webhook_verify_token=client_data.webhook_verify_token,
                logo_url=client_data.logo_url,
                is_crm_enabled=client_data.is_crm_enabled,
                admin_limit=client_data.admin_limit,
                is_premium=client_data.is_premium,
                subscription_expiry=client_data.subscription_expiry,
                status=client_data.status
            )
            session.add(new_client)
            
            # Create wallet
            new_wallet = Wallet(client_id=new_client.client_id, balance=client_data.wallet_balance)
            session.add(new_wallet)
            
            await session.commit()
            return {"success": True, "clientId": new_client.client_id}
        except Exception as e:
            logger.error(f"Error adding client: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/updateClient")
async def update_client(clientId: str = Query(...), client_data: ClientUpdate = Body(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Client).where(Client.client_id == clientId)
            )
            client = result.scalars().first()
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")
            
            update_dict = client_data.dict(exclude_none=True)
            for key, value in update_dict.items():
                if key != "wallet_balance" and hasattr(client, key):
                    setattr(client, key, value)
            
            # Handle wallet update
            if "wallet_balance" in update_dict:
                wallet_result = await session.execute(
                    select(Wallet).where(Wallet.client_id == clientId)
                )
                wallet = wallet_result.scalars().first()
                if wallet:
                    wallet.balance = update_dict["wallet_balance"]
                else:
                    new_wallet = Wallet(client_id=clientId, balance=update_dict["wallet_balance"])
                    session.add(new_wallet)

            client.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating client: {e}")
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

@router.patch("/patchClient")
async def patch_client(clientId: str = Query(...), client_data: ClientUpdate = Body(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Client).where(Client.client_id == clientId)
            )
            client = result.scalars().first()
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")
            
            update_dict = client_data.dict(exclude_none=True)
            for key, value in update_dict.items():
                if key != "wallet_balance" and hasattr(client, key):
                    setattr(client, key, value)
            
            # Handle wallet update
            if "wallet_balance" in update_dict:
                wallet_result = await session.execute(
                    select(Wallet).where(Wallet.client_id == clientId)
                )
                wallet = wallet_result.scalars().first()
                if wallet:
                    wallet.balance = update_dict["wallet_balance"]
                else:
                    new_wallet = Wallet(client_id=clientId, balance=update_dict["wallet_balance"])
                    session.add(new_wallet)

            client.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error patching client: {e}")
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

@router.delete("/deleteClient")
async def delete_client(clientId: str = Query(...)):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Client).where(Client.client_id == clientId)
            )
            client = result.scalars().first()
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")
            
            await session.delete(client)
            await session.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting client: {e}")
            raise HTTPException(status_code=500, detail=str(e))
