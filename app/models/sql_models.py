from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON, Float, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import datetime

class Client(Base):
    __tablename__ = "clients"

    client_id = Column(String, primary_key=True, index=True)
    waba_id = Column(String)
    phone_number_id = Column(String)
    phone_number = Column(String)
    webhook_verify_token = Column(String)
    store_id = Column(String)
    qna_store_id = Column(String)
    google_api_key = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    contacts = relationship("Contact", back_populates="client")
    chats = relationship("Chat", back_populates="client")
    templates = relationship("Template", back_populates="client")
    broadcasts = relationship("Broadcast", back_populates="client")
    wallet = relationship("Wallet", uselist=False, back_populates="client")

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, index=True) # Using string ID to match Firestore IDs if needed, or UUID
    client_id = Column(String, ForeignKey("clients.client_id"))
    
    phone_number = Column(String, index=True)
    country_code = Column(String)
    f_name = Column(String)
    l_name = Column(String)
    email = Column(String)
    company = Column(String)
    notes = Column(Text)
    tags = Column(JSON, default=list) # Store as JSON array
    status = Column(Integer, nullable=True) # 0: stop, 1: resume
    last_contacted = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    status_updated_at = Column(DateTime(timezone=True))
    
    # Milestone Fields
    birthdate_month = Column(String)
    anniversary_date_month = Column(String)
    work_anniversary_date_month = Column(String)
    is_birthdate_active = Column(Boolean, default=True)
    is_anniversary_active = Column(Boolean, default=True)
    is_work_anniversary_active = Column(Boolean, default=True)
    profile_photo = Column(String)
    birth_date = Column(String)
    anniversary_dt = Column(String)

    client = relationship("Client", back_populates="contacts")
    chats = relationship("Chat", back_populates="contact")

class MilestoneScheduler(Base):
    __tablename__ = "milestone_schedulers"
    
    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.client_id"))
    type = Column(String)
    background_url = Column(Text)
    elements = Column(JSON)
    variable_values = Column(JSON)
    selected_template_name = Column(String)
    language = Column(String)
    last_run = Column(DateTime(timezone=True))
    
    image_width = Column(Float)
    image_height = Column(Float)
    background_scale = Column(Float)

class UnansweredQuestion(Base):
    __tablename__ = "unanswered_questions"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String, ForeignKey("clients.client_id"))
    contact_id = Column(String)
    question = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())



class Chat(Base):
    __tablename__ = "chats"

    id = Column(String, primary_key=True) # Usually contact_id
    client_id = Column(String, ForeignKey("clients.client_id"))
    contact_id = Column(String, ForeignKey("contacts.id"))

    name = Column(String)
    phone_number = Column(String)
    avatar_url = Column(String)
    last_message = Column(Text)
    last_message_time = Column(DateTime(timezone=True))
    campaign_name = Column(String)
    is_online = Column(Boolean, default=False)
    ai_response_enabled = Column(Boolean, default=False)
    is_active = Column(Boolean, default=False)
    un_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user_last_message_time = Column(DateTime(timezone=True))

    client = relationship("Client", back_populates="chats")
    contact = relationship("Contact", back_populates="chats")
    messages = relationship("Message", back_populates="chat")

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True) # Internal DB ID
    # OR we can use whatsapp_message_id as PK, but easier to have int PK
    
    chat_id = Column(String, ForeignKey("chats.id"), index=True)
    client_id = Column(String, ForeignKey("clients.client_id"))
    
    content = Column(Text)
    timestamp = Column(DateTime(timezone=True))
    is_from_me = Column(Boolean)
    sender_name = Column(String)
    sender_avatar = Column(String)
    status = Column(String) # sent, delivered, read, failed
    whatsapp_message_id = Column(String, index=True, nullable=True)
    
    message_type = Column(String) # text, image, document, video, audio, etc.
    media_url = Column(Text)
    file_name = Column(String)
    mime_type = Column(String)
    caption = Column(Text)
    context = Column(JSON) # Reply context
    
    delivered_at = Column(DateTime(timezone=True))
    read_at = Column(DateTime(timezone=True))
    sent_at = Column(DateTime(timezone=True))
    failed_at = Column(DateTime(timezone=True))
    
    error_code = Column(Integer)
    error_description = Column(Text)

    chat = relationship("Chat", back_populates="messages")

class Template(Base):
    __tablename__ = "templates"

    id = Column(String, primary_key=True) # Template ID or name
    client_id = Column(String, ForeignKey("clients.client_id"))
    
    name = Column(String)
    category = Column(String)
    components = Column(JSON)
    status = Column(String)
    language = Column(String)
    reason = Column(JSON)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    type = Column(String) # Text & Media, etc

    client = relationship("Client", back_populates="templates")

class Broadcast(Base):
    __tablename__ = "broadcasts"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.client_id"))
    
    template_id = Column(String)
    admin_name = Column(String)
    attachment_id = Column(String)
    
    audience_type = Column(Integer)
    contact_ids = Column(JSON) # Array of strings
    
    sent = Column(Integer, default=0)
    delivered = Column(Integer, default=0)
    read = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    
    status = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    client = relationship("Client", back_populates="broadcasts")
    messages = relationship("BroadcastMessage", back_populates="broadcast")

class BroadcastMessage(Base):
    __tablename__ = "broadcast_messages"

    id = Column(String, primary_key=True) # Message ID
    broadcast_id = Column(String, ForeignKey("broadcasts.id"))
    client_id = Column(String)
    
    payload = Column(JSON)
    status = Column(String)
    whatsapp_message_id = Column(String, index=True)
    
    delivered_at = Column(DateTime(timezone=True))
    read_at = Column(DateTime(timezone=True))
    sent_at = Column(DateTime(timezone=True))
    failed_at = Column(DateTime(timezone=True))
    
    cost = Column(Float, default=0.0)
    added_to_chat = Column(Boolean, default=False)
    
    error_code = Column(Integer)
    
    broadcast = relationship("Broadcast", back_populates="messages")

class DailyStats(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, ForeignKey("clients.client_id"))
    date = Column(String) # YYYY-MM-DD
    
    total_sent = Column(Integer, default=0)
    total_delivered = Column(Integer, default=0)
    total_read = Column(Integer, default=0)
    total_failed = Column(Integer, default=0)
    
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String)
    type = Column(String)
    payload = Column(JSON)
    status = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Wallet(Base):
    __tablename__ = "wallet"

    client_id = Column(String, ForeignKey("clients.client_id"), primary_key=True)
    balance = Column(Float, default=0.0)
    
    client = relationship("Client", back_populates="wallet")
    history = relationship("WalletHistory", back_populates="wallet")

class WalletHistory(Base):
    __tablename__ = "wallet_history"
    
    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("wallet.client_id"))
    
    broadcast_id = Column(String)
    chargeable_messages = Column(Integer)
    chargeable_amount = Column(Float)
    
    wallet = relationship("Wallet", back_populates="history")
