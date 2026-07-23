from fastapi import APIRouter, Request, Response, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.future import select
from app.database import AsyncSessionLocal
from app.models.sql_models import UnansweredQuestion
from app.services.utils import get_secrets
from google import genai
from google.genai import types
import os
import shutil
import time
import logging
import datetime
from typing import Optional

router = APIRouter(prefix="/chatbot", tags=["chatbot"])
logger = logging.getLogger(__name__)

def get_target_store_id(is_qna: bool, secrets: dict) -> Optional[str]:
    return secrets.get("qnaStoreId") if is_qna else secrets.get("storeId")

@router.post("/create")
async def create_chatbot_store(payload: dict):
    display_name = payload.get("displayName")
    # Use the system's global GOOGLE_API_KEY for store creation
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="System Google API Key is not configured in .env")
        
    try:
        client = genai.Client(api_key=api_key)
        store = client.file_search_stores.create(
            config={'display_name': display_name}
        )
        return {
            "success": True,
            "message": "FileSearchStore created successfully.",
            "data": {
                "id": store.name
            }
        }
    except Exception as e:
        logger.error(f"Error creating FileSearchStore: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list")
async def list_documents(
    clientId: str = Query(...),
    isQnA: str = Query("false"),
    pageSize: Optional[int] = Query(None),
    pageToken: Optional[str] = Query(None)
):
    is_qna = isQnA.lower() == "true"
    secrets = await get_secrets(clientId)
    if not secrets:
        raise HTTPException(status_code=404, detail="Client not found")
        
    api_key = secrets.get("googleApiKey")
    target_store_id = get_target_store_id(is_qna, secrets)
    
    if not api_key:
        raise HTTPException(status_code=400, detail="Client's Google API Key is not configured")
    if not target_store_id:
        raise HTTPException(status_code=400, detail="Target store ID is not configured")
        
    try:
        client = genai.Client(api_key=api_key)
        
        # Call Google API
        response = client.file_search_stores.documents.list(parent=target_store_id)
        
        data = []
        # Python SDK lists documents as a generator
        for doc in response:
            description = ""
            if doc.custom_metadata:
                # custom_metadata can be list of structures or dicts
                for meta in doc.custom_metadata:
                    if meta.key == "description":
                        description = meta.string_value
                        break
            
            date_uploaded = ""
            if doc.create_time:
                try:
                    # format in IST time zone
                    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
                    ist_time = doc.create_time.astimezone(ist)
                    date_uploaded = ist_time.strftime("%d/%m/%Y, %I:%M:%S %p")
                except Exception:
                    date_uploaded = str(doc.create_time)
                    
            data.append({
                "id": doc.name,
                "fileName": doc.display_name,
                "fileMimeType": doc.mime_type,
                "description": description,
                "dateUploaded": date_uploaded
            })
            
        return {
            "success": True,
            "data": data
        }
    except Exception as e:
        logger.error(f"Error listing chatbot documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_documents(request: Request):
    try:
        form = await request.form()
        client_id = form.get("clientId")
        is_qna = form.get("isQnA") == "true" or form.get("isQnA") is True
        description = form.get("description")
        
        if not client_id:
            raise HTTPException(status_code=400, detail="Missing clientId")
            
        secrets = await get_secrets(client_id)
        if not secrets:
            raise HTTPException(status_code=404, detail="Client not found")
            
        api_key = secrets.get("googleApiKey")
        target_store_id = get_target_store_id(is_qna, secrets)
        
        if not api_key:
            raise HTTPException(status_code=400, detail="Client's Google API Key is missing")
        if not target_store_id:
            raise HTTPException(status_code=400, detail="Target File Search Store is missing")
            
        # Collect uploaded files
        uploaded_files = []
        for key, value in form.items():
            if key.startswith("file") and isinstance(value, UploadFile):
                uploaded_files.append(value)
                
        if not uploaded_files:
            raise HTTPException(status_code=400, detail="No files uploaded")
            
        client = genai.Client(api_key=api_key)
        
        os.makedirs("temp", exist_ok=True)
        ids = []
        
        for ufile in uploaded_files:
            temp_path = f"temp/{ufile.filename}"
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(ufile.file, buffer)
                
            config = {'display_name': ufile.filename}
            if description:
                config['custom_metadata'] = [{'key': 'description', 'string_value': description}]
                
            operation = client.file_search_stores.upload_to_file_search_store(
                file=temp_path,
                file_search_store_name=target_store_id,
                config=config
            )
            
            # Wait for completion
            while not operation.done:
                time.sleep(1)
                operation = client.operations.get(operation)
                
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            doc_name = operation.response.name if operation.response else ""
            ids.append(doc_name)
            
        return {
            "success": True,
            "data": {
                "ids": ids
            }
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error uploading chatbot documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/delete")
async def delete_document(payload: dict):
    client_id = payload.get("clientId")
    doc_id = payload.get("id")
    
    if not client_id or not doc_id:
         raise HTTPException(status_code=400, detail="Missing clientId or id")
         
    secrets = await get_secrets(client_id)
    if not secrets:
        raise HTTPException(status_code=404, detail="Client not found")
        
    api_key = secrets.get("googleApiKey")
    if not api_key:
        raise HTTPException(status_code=400, detail="Client's Google API Key is missing")
        
    try:
        client = genai.Client(api_key=api_key)
        client.file_search_stores.documents.delete(name=doc_id)
        return {
            "success": True,
            "message": f"Document {doc_id} deleted successfully."
        }
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/update")
async def update_document(request: Request):
    try:
        form = await request.form()
        client_id = form.get("clientId")
        is_qna = form.get("isQnA") == "true" or form.get("isQnA") is True
        doc_id = form.get("id")
        description = form.get("description")
        
        uploaded_file = None
        for key, value in form.items():
            if key.startswith("file") and isinstance(value, UploadFile):
                uploaded_file = value
                break
                
        if not client_id or not doc_id or not uploaded_file:
            raise HTTPException(status_code=400, detail="Missing clientId, id, or file")
            
        secrets = await get_secrets(client_id)
        if not secrets:
            raise HTTPException(status_code=404, detail="Client not found")
            
        api_key = secrets.get("googleApiKey")
        target_store_id = get_target_store_id(is_qna, secrets)
        
        if not api_key or not target_store_id:
             raise HTTPException(status_code=400, detail="Missing googleApiKey or store configuration")
             
        client = genai.Client(api_key=api_key)
        
        # 1. Delete old document
        try:
            client.file_search_stores.documents.delete(name=doc_id)
        except Exception as delete_err:
            logger.warning(f"Failed to delete old document {doc_id}: {delete_err}")
            
        # 2. Upload new document
        os.makedirs("temp", exist_ok=True)
        temp_path = f"temp/{uploaded_file.filename}"
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(uploaded_file.file, buffer)
            
        config = {'display_name': uploaded_file.filename}
        if description:
            config['custom_metadata'] = [{'key': 'description', 'string_value': description}]
            
        operation = client.file_search_stores.upload_to_file_search_store(
            file=temp_path,
            file_search_store_name=target_store_id,
            config=config
        )
        
        while not operation.done:
            time.sleep(1)
            operation = client.operations.get(operation)
            
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        new_doc_name = operation.response.name if operation.response else ""
        return {
            "success": True,
            "message": "File updated successfully (old deleted, new uploaded)",
            "data": {
                "id": new_doc_name
            }
        }
    except Exception as e:
        logger.error(f"Error updating document: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/questions/update")
async def update_question(payload: dict):
    client_id = payload.get("clientId")
    question_id = payload.get("questionId")
    update_data = payload.get("data", {})
    
    if not client_id or not question_id:
        raise HTTPException(status_code=400, detail="Missing clientId or questionId")
        
    async with AsyncSessionLocal() as session:
        try:
            # Look up unanswered question by primary key (int)
            result = await session.execute(
                select(UnansweredQuestion).where(
                    UnansweredQuestion.id == int(question_id),
                    UnansweredQuestion.client_id == client_id
                )
            )
            uq = result.scalars().first()
            if not uq:
                raise HTTPException(status_code=404, detail="Question not found")
                
            # Perform updates
            # If status or answer are inside update_data
            if "status" in update_data:
                uq.status = update_data["status"]
            if "answer" in update_data:
                uq.answer = update_data["answer"]
            
            # Map whenAnswered / FieldValue.serverTimestamp() or FieldValue.delete()
            # If we receive whenAnswered we set it to current IST time
            if "whenAnswered" in update_data:
                ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
                uq.when_answered = datetime.datetime.now(ist)
            elif "whenAnswered" not in update_data and uq.status == "pending":
                uq.when_answered = None
                
            await session.commit()
            
            # Real-time sync to Firestore
            from app.services.firebase_service import db
            from firebase_admin import firestore
            if db:
                ref = db.collection("unanswered_questions").document(client_id).collection("data").document(str(uq.id))
                
                # Build Firestore payload
                doc_payload = {
                    "contactId": uq.contact_id,
                    "question": uq.question,
                    "status": uq.status,
                }
                
                if uq.answer:
                    doc_payload["answer"] = uq.answer
                else:
                    doc_payload["answer"] = firestore.firestore.DELETE_FIELD
                    
                if uq.when_answered:
                    doc_payload["whenAnswered"] = uq.when_answered
                else:
                    doc_payload["whenAnswered"] = firestore.firestore.DELETE_FIELD
                    
                ref.set(doc_payload, merge=True)
                
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating question: {e}")
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/questions/delete")
async def delete_question(payload: dict):
    client_id = payload.get("clientId")
    question_id = payload.get("questionId")
    
    if not client_id or not question_id:
        raise HTTPException(status_code=400, detail="Missing clientId or questionId")
        
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(UnansweredQuestion).where(
                    UnansweredQuestion.id == int(question_id),
                    UnansweredQuestion.client_id == client_id
                )
            )
            uq = result.scalars().first()
            if not uq:
                raise HTTPException(status_code=404, detail="Question not found")
                
            await session.delete(uq)
            await session.commit()
            
            # Sync deletion to Firestore
            from app.services.firebase_service import db
            if db:
                ref = db.collection("unanswered_questions").document(client_id).collection("data").document(str(question_id))
                ref.delete()
                
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting question: {e}")
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))
