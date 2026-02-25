from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

# --- Client Schemas ---
class ClientBase(BaseModel):
    client_id: str
    waba_id: Optional[str] = None
    phone_number_id: Optional[str] = None
    phone_number: Optional[str] = None
    webhook_verify_token: Optional[str] = None
    store_id: Optional[str] = None
    qna_store_id: Optional[str] = None
    google_api_key: Optional[str] = None
    name: Optional[str] = "Messaging Portal"
    logo_url: Optional[str] = None
    is_crm_enabled: Optional[bool] = False

class ClientCreate(ClientBase):
    pass

class ClientUpdate(BaseModel):
    waba_id: Optional[str] = None
    phone_number_id: Optional[str] = None
    phone_number: Optional[str] = None
    webhook_verify_token: Optional[str] = None
    store_id: Optional[str] = None
    qna_store_id: Optional[str] = None
    google_api_key: Optional[str] = None
    name: Optional[str] = None
    logo_url: Optional[str] = None
    is_crm_enabled: Optional[bool] = None

class Client(ClientBase):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Charge Schemas ---
class RoleBase(BaseModel):
    role_name: str
    client_id: str
    assigned_pages: List[Dict[str, Any]] = []

class RoleCreate(RoleBase):
    id: Optional[str] = None

class RoleUpdate(BaseModel):
    role_name: Optional[str] = None
    assigned_pages: Optional[List[Dict[str, Any]]] = None

class Role(RoleBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ChargeBase(BaseModel):
    id: str
    name: str
    price: float
    description: Optional[str] = None

class ChargeCreate(ChargeBase):
    pass

class Charge(ChargeBase):
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Auth Schemas ---
class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    success: bool
    token: str
    admin: Dict[str, Any]
    clientId: str

# --- Contact Schemas ---
class ContactBase(BaseModel):
    id: str
    client_id: str
    phone_number: str
    country_code: Optional[str] = None
    f_name: Optional[str] = None
    l_name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    tags: List[Any] = []
    status: Optional[int] = None
    profile_photo: Optional[str] = None
    
    # Milestone Fields
    birthdate_month: Optional[str] = None
    anniversary_date_month: Optional[str] = None
    work_anniversary_date_month: Optional[str] = None
    is_birthdate_active: Optional[bool] = True
    is_anniversary_active: Optional[bool] = True
    is_work_anniversary_active: Optional[bool] = True
    birth_date: Optional[str] = None
    anniversary_dt: Optional[str] = None

class ContactCreate(ContactBase):
    pass

class ContactUpdate(BaseModel):
    phone_number: Optional[str] = None
    country_code: Optional[str] = None
    f_name: Optional[str] = None
    l_name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[Any]] = None
    status: Optional[int] = None
    profile_photo: Optional[str] = None
    last_contacted: Optional[datetime] = None
    status_updated_at: Optional[datetime] = None
    
    # Milestone Fields
    birthdate_month: Optional[str] = None
    anniversary_date_month: Optional[str] = None
    work_anniversary_date_month: Optional[str] = None
    is_birthdate_active: Optional[bool] = None
    is_anniversary_active: Optional[bool] = None
    is_work_anniversary_active: Optional[bool] = None
    birth_date: Optional[str] = None
    anniversary_dt: Optional[str] = None

class Contact(ContactBase):
    last_contacted: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    status_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Milestone Scheduler Schemas ---
class MilestoneSchedulerBase(BaseModel):
    id: str
    client_id: str
    type: str # birthday, anniversary, etc.
    background_url: Optional[str] = None
    elements: List[Any] = []
    variable_values: Any = None
    selected_template_name: Optional[str] = None
    language: Optional[str] = None
    
    image_width: Optional[float] = None
    image_height: Optional[float] = None
    background_scale: Optional[float] = None

class MilestoneSchedulerCreate(MilestoneSchedulerBase):
    pass

class MilestoneSchedulerUpdate(BaseModel):
    background_url: Optional[str] = None
    elements: Optional[List[Any]] = None
    variable_values: Optional[Any] = None
    selected_template_name: Optional[str] = None
    language: Optional[str] = None
    last_run: Optional[datetime] = None
    image_width: Optional[float] = None
    image_height: Optional[float] = None
    background_scale: Optional[float] = None

class MilestoneScheduler(MilestoneSchedulerBase):
    last_run: Optional[datetime] = None

    class Config:
        from_attributes = True

class MilestoneTriggerRequest(BaseModel):
    clientId: str
    schedulerId: str

# --- Unanswered Question Schemas ---
class UnansweredQuestionBase(BaseModel):
    client_id: str
    contact_id: str
    question: str

class UnansweredQuestionCreate(UnansweredQuestionBase):
    pass

class UnansweredQuestion(UnansweredQuestionBase):
    id: int
    timestamp: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Chat Schemas ---
class ChatBase(BaseModel):
    id: str # contact_id
    client_id: str
    contact_id: str
    name: Optional[str] = None
    phone_number: Optional[str] = None
    avatar_url: Optional[str] = None
    campaign_name: Optional[str] = None
    is_online: Optional[bool] = False
    ai_response_enabled: Optional[bool] = False
    is_active: Optional[bool] = False
    un_read: Optional[bool] = False

class ChatCreate(ChatBase):
    last_message: Optional[str] = None
    last_message_time: Optional[datetime] = None

class ChatUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    last_message: Optional[str] = None
    last_message_time: Optional[datetime] = None
    user_last_message_time: Optional[datetime] = None
    is_online: Optional[bool] = None
    ai_response_enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    un_read: Optional[bool] = None

class Chat(ChatBase):
    last_message: Optional[str] = None
    last_message_time: Optional[datetime] = None
    created_at: Optional[datetime] = None
    user_last_message_time: Optional[datetime] = None

    class Config:
        from_attributes = True

class SendMessageRequest(BaseModel):
    clientId: str
    phoneNumber: str
    chatId: str
    message: str
    messageType: str = "text"
    mediaUrl: Optional[str] = None
    fileName: Optional[str] = None

class UploadMediaRequest(BaseModel):
    clientId: str
    fileName: str
    mimeType: str
    base64File: str

class UpdateMessageStatusRequest(BaseModel):
    clientId: str
    whatsappMessageId: str
    status: str

# --- Message Schemas ---
class MessageBase(BaseModel):
    chat_id: str
    client_id: str
    content: Optional[str] = None
    is_from_me: bool
    sender_name: Optional[str] = None
    sender_avatar: Optional[str] = None
    status: Optional[str] = None
    whatsapp_message_id: Optional[str] = None
    message_type: Optional[str] = None
    media_url: Optional[str] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    caption: Optional[str] = None
    context: Optional[Any] = None
    
class MessageCreate(MessageBase):
    timestamp: Optional[datetime] = None

class MessageUpdate(BaseModel):
    status: Optional[str] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_code: Optional[int] = None
    error_description: Optional[str] = None

class Message(MessageBase):
    id: int
    timestamp: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_code: Optional[int] = None
    error_description: Optional[str] = None

    class Config:
        from_attributes = True

# --- Template Schemas ---
class TemplateBase(BaseModel):
    id: str
    client_id: str
    name: Optional[str] = None
    category: Optional[str] = None
    components: Optional[List[Any]] = None
    status: Optional[str] = None
    language: Optional[str] = None
    reason: Optional[Any] = None
    type: Optional[str] = None

class TemplateCreate(BaseModel):
    clientId: str
    name: str # Template Name
    language: str
    category: str
    templateType: Optional[str] = "Text"
    header: Optional[str] = None
    body: str
    footer: Optional[str] = None
    buttons: Optional[List[Dict]] = None
    # For media
    media_handle_id: Optional[str] = None
    mediaType: Optional[str] = None
    
    # Extra fields that might be passed
    bodyExampleValues: Optional[List[Any]] = None

class DeleteTemplateRequest(BaseModel):
    name: Optional[str] = None
    clientId: Optional[str] = None

class Template(TemplateBase):
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Broadcast Schemas ---
class BroadcastBase(BaseModel):
    id: str
    client_id: str
    template_id: Optional[str] = None
    admin_name: Optional[str] = None
    attachment_id: Optional[str] = None
    audience_type: Optional[int] = None
    contact_ids: Optional[List[str]] = None
    status: Optional[str] = None

class BroadcastCreate(BroadcastBase):
    pass

class BroadcastUpdate(BaseModel):
    sent: Optional[int] = None
    delivered: Optional[int] = None
    read: Optional[int] = None
    failed: Optional[int] = None
    status: Optional[str] = None

class Broadcast(BroadcastBase):
    sent: Optional[int] = 0
    delivered: Optional[int] = 0
    read: Optional[int] = 0
    failed: Optional[int] = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class BroadcastMessageBase(BaseModel):
    id: str
    broadcast_id: str
    client_id: str
    payload: Optional[Any] = None
    status: Optional[str] = None
    whatsapp_message_id: Optional[str] = None
    cost: Optional[float] = 0.0
    added_to_chat: Optional[bool] = False

class BroadcastMessage(BroadcastMessageBase):
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_code: Optional[int] = None

    class Config:
        from_attributes = True

# --- Stats & Logs Schemas ---
class DailyStatsBase(BaseModel):
    client_id: str
    date: str
    total_sent: Optional[int] = 0
    total_delivered: Optional[int] = 0
    total_read: Optional[int] = 0
    total_failed: Optional[int] = 0

class DailyStats(DailyStatsBase):
    id: int
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class WebhookLogBase(BaseModel):
    client_id: str
    type: str
    payload: Optional[Any] = None
    status: Optional[str] = None

class WebhookLog(WebhookLogBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Wallet Schemas ---
class WalletBase(BaseModel):
    client_id: str
    balance: float = 0.0

class Wallet(WalletBase):
    class Config:
        from_attributes = True

class WalletHistoryBase(BaseModel):
    id: str
    client_id: str
    broadcast_id: Optional[str] = None
    chargeable_messages: Optional[int] = None
    chargeable_amount: Optional[float] = None

class WalletHistory(WalletHistoryBase):
    class Config:
        from_attributes = True

# --- Generic Response Wrappers ---

class ResponseModel(BaseModel):
    success: bool
    message: Optional[str] = None
    data: Optional[Any] = None

# --- New Documentation Schemas ---

class WebhookMetadata(BaseModel):
    display_phone_number: str
    phone_number_id: str

class WebhookValue(BaseModel):
    messaging_product: str
    metadata: WebhookMetadata
    contacts: Optional[List[Dict[str, Any]]] = None
    messages: Optional[List[Dict[str, Any]]] = None
    statuses: Optional[List[Dict[str, Any]]] = None

class WebhookChange(BaseModel):
    value: WebhookValue
    field: str

class WebhookEntry(BaseModel):
    id: str
    changes: List[WebhookChange]

class MetaWebhookPayload(BaseModel):
    object: str
    entry: List[WebhookEntry]

class BroadcastStartRequest(BaseModel):
    clientId: str
    broadcastId: str

class BroadcastCreateRequest(BaseModel):
    clientId: str
    templateId: Optional[str] = None
    templateName: Optional[str] = None
    language: Optional[str] = None
    type: Optional[str] = None # Text, Media, Interactive
    adminName: Optional[str] = None
    attachmentId: Optional[str] = None
    audienceType: Optional[int] = None
    contacts: Optional[List[Dict[str, Any]]] = None # List of {mobileNo, bodyVariables}
    headerVariables: Optional[Dict[str, Any]] = None
    buttonVariables: Optional[List[Any]] = None
    messageCost: Optional[float] = 0.0
    totalCost: Optional[float] = 0.0

class AnalyticsRequest(BaseModel):
    clientId: str
    filter: Optional[str] = "This Month"
    customStart: Optional[str] = None
    customEnd: Optional[str] = None

class PhoneNumberRequest(BaseModel):
    phoneNumber: str

class SendTemplateMessageRequest(BaseModel):
    clientId: str
    templateName: str
    language: str
    phoneNumber: str
    bodyVariables: Optional[List[str]] = None
    headerVariables: Optional[Dict[str, Any]] = None # Matches broadcastHandler.js format
    buttonVariables: Optional[List[Dict[str, Any]]] = None # Matches broadcastHandler.js format
    # Optional direct fields for simpler usage
    mediaId: Optional[str] = None
    mediaType: Optional[str] = "image"
    headerText: Optional[str] = None
class UpdateChatRequest(BaseModel):
    clientId: str
    chatId: str
    isActive: Optional[bool] = None
    unRead: Optional[bool] = None
    isFavourite: Optional[bool] = None
    assignedAdmins: Optional[List[str]] = None

# --- Admin Schemas ---
class AdminBase(BaseModel):
    id: str
    client_id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_photo: Optional[str] = None

class AdminCreate(AdminBase):
    password: str

class AdminUpdate(BaseModel):
    client_id: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_photo: Optional[str] = None
    password: Optional[str] = None
    is_super_user: Optional[bool] = None
    is_all_chats: Optional[bool] = None
    assigned_pages: Optional[List[str]] = None
    assigned_contacts: Optional[List[str]] = None

class Admin(AdminBase):
    assigned_contacts: List[str] = []
    is_super_user: bool = False
    is_all_chats: bool = False
    assigned_pages: List[str] = []
    last_logged_in: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
