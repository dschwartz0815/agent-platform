from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

_is_sqlite = "sqlite" in settings.database_url

engine = create_async_engine(
    settings.database_url,
    # Only emit SQL when LOG_LEVEL=DEBUG is explicitly requested
    echo=settings.log_level.upper() == "DEBUG",
    # Verify connections before use — critical for Postgres pools after idle time
    pool_pre_ping=True,
    # SQLite requires check_same_thread=False for use across asyncio tasks
    **({"connect_args": {"check_same_thread": False}} if _is_sqlite else {}),
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
