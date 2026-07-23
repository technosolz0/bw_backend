from dotenv import load_dotenv
load_dotenv()

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
        await conn.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_bot_activated BOOLEAN DEFAULT FALSE;")
        await conn.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_upload_questions_enabled BOOLEAN DEFAULT FALSE;")
        await conn.execute("ALTER TABLE unanswered_questions ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'pending';")
        await conn.execute("ALTER TABLE unanswered_questions ADD COLUMN IF NOT EXISTS answer JSON DEFAULT NULL;")
        await conn.execute("ALTER TABLE unanswered_questions ADD COLUMN IF NOT EXISTS when_answered TIMESTAMP WITH TIME ZONE DEFAULT NULL;")

