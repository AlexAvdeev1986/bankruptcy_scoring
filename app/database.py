from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Синхронный движок для операций записи
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True
)

# Асинхронный движок для операций чтения
async_engine = create_async_engine(
    settings.DATABASE_URL.replace("postgresql", "postgresql+asyncpg"),
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True
)

# Синхронная сессия
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Асинхронная сессия
AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

Base = declarative_base()

def get_db():
    """Синхронная сессия для операций записи"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_async_db():
    """Асинхронная сессия для операций чтения"""
    async with AsyncSessionLocal() as session:
        yield session
        