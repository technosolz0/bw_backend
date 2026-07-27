from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://bw_user:BusinessW7558726131@127.0.0.1:5432/bw_db"
)

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Ensure new columns exist on client table
        await conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_bot_activated BOOLEAN DEFAULT FALSE;"))
        await conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_upload_questions_enabled BOOLEAN DEFAULT FALSE;"))
        await conn.execute(text("ALTER TABLE unanswered_questions ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'pending';"))
        await conn.execute(text("ALTER TABLE unanswered_questions ADD COLUMN IF NOT EXISTS answer JSON DEFAULT NULL;"))
        await conn.execute(text("ALTER TABLE unanswered_questions ADD COLUMN IF NOT EXISTS when_answered TIMESTAMP WITH TIME ZONE DEFAULT NULL;"))
        
        # Ensure new columns exist on broadcasts table
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS broadcast_name VARCHAR;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS description VARCHAR;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS invocation_failures INTEGER DEFAULT 0;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS template_variables JSON;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS media_id VARCHAR;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS delivery_type INTEGER;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS delivery_timestamp TIMESTAMP WITH TIME ZONE;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS total_cost DOUBLE PRECISION DEFAULT 0.0;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS clicks INTEGER DEFAULT 0;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS replied INTEGER DEFAULT 0;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS enable_retry BOOLEAN DEFAULT FALSE;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS retry_campaign_status VARCHAR;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS card_variables JSON;"))
        await conn.execute(text("ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS card_attachment_ids JSON;"))

