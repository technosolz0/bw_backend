import firebase_admin
from firebase_admin import credentials, firestore
import logging
import os
import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Initialize Firebase Admin
_firebase_app = None
db: Optional[firestore.client] = None

def init_firebase():
    global _firebase_app, db
    try:
        key_path = os.getenv("FIREBASE_KEY_PATH", "firebase_key.json")
        if not os.path.exists(key_path):
            logger.warning(f"Firebase key file not found at {key_path}. Firestore sync will be disabled.")
            return

        cred = credentials.Certificate(key_path)
        _firebase_app = firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("Firebase Admin initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing Firebase Admin: {e}")

async def sync_chat_metadata(chat_id: str, client_id: str, metadata: Dict[str, Any]):
    """Sync chat metadata (last message, update time, etc.) to Firestore."""
    if not db:
        logger.debug("Firestore sync disabled: db not initialized.")
        return
    
    try:
        # Use a flat structure or nested? Reference project used 'chats' collection
        chat_ref = db.collection("chats").document(chat_id)
        
        # Add client_id filter if needed, but chat_id is usually unique per contact
        # Adding metadata
        metadata["updatedAt"] = firestore.SERVER_TIMESTAMP
        metadata["clientId"] = client_id
        
        chat_ref.set(metadata, merge=True)
        logger.info(f"✅ Chat metadata synced to Firestore for chat {chat_id}")
    except Exception as e:
        logger.error(f"❌ Error syncing chat metadata for {chat_id} to Firestore: {e}", exc_info=True)

async def sync_message(chat_id: str, client_id: str, message_id: str, message_data: Dict[str, Any]):
    """Sync a single message to Firestore."""
    if not db:
        logger.debug("Firestore sync disabled: db not initialized.")
        return
    
    try:
        message_ref = db.collection("chats").document(chat_id).collection("messages").document(message_id)
        
        # Convert datetime objects to Firestore-compatible if necessary
        # message_data["timestamp"] should be handled by caller or here
        if "timestamp" in message_data and isinstance(message_data["timestamp"], datetime.datetime):
             # Ensure it's not naive for Firestore
             if message_data["timestamp"].tzinfo is None:
                 message_data["timestamp"] = message_data["timestamp"].replace(tzinfo=datetime.timezone.utc)
        
        message_data["clientId"] = client_id
        message_ref.set(message_data)
        logger.info(f"✅ Message {message_id} synced to Firestore for chat {chat_id}")
    except Exception as e:
        logger.error(f"❌ Error syncing message {message_id} to Firestore: {e}", exc_info=True)

async def sync_message_status(chat_id: str, message_id: str, status: str, timestamp: Optional[datetime.datetime] = None):
    """Update message status in Firestore."""
    if not db:
        return
    
    try:
        message_ref = db.collection("chats").document(chat_id).collection("messages").document(message_id)
        
        updates = {"status": status}
        if status == "delivered":
            updates["deliveredAt"] = timestamp or firestore.SERVER_TIMESTAMP
        elif status == "read":
            updates["readAt"] = timestamp or firestore.SERVER_TIMESTAMP
            
        message_ref.update(updates)
    except Exception as e:
        logger.error(f"Error updating message status in Firestore: {e}")

async def sync_broadcast_stats(broadcast_id: str, client_id: str, stats: Dict[str, Any]):
    """Sync broadcast statistics to Firestore."""
    if not db:
        return
    
    try:
        broadcast_ref = db.collection("broadcasts").document(broadcast_id)
        stats["updatedAt"] = firestore.SERVER_TIMESTAMP
        stats["clientId"] = client_id
        
        broadcast_ref.set(stats, merge=True)
    except Exception as e:
        logger.error(f"Error syncing broadcast stats to Firestore: {e}")
