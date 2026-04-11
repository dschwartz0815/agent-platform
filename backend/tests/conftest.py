"""
Shared pytest fixtures.

- A fresh in-memory SQLite database per test via a session-scoped engine
  with function-scoped `SAVEPOINT` rollbacks (no data bleeds between tests).
- An httpx.AsyncClient wired to the FastAPI app via ASGITransport so we can
  hit endpoints directly without running uvicorn.
- Alembic migrations applied once at session start.
"""

import importlib
import os
import sys

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Set the DB URL BEFORE any app modules are imported
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DEBUG"] = "false"  # disable seed during tests — tests set up their own data
os.environ["ANTHROPIC_API_KEY"] = "test-key"

# If app modules are already imported (from the background app process), reload them
# This is important because Settings() instances are singletons that read from env at init time
if "app.config" in sys.modules:
    importlib.reload(sys.modules["app.config"])
if "app.db" in sys.modules:
    importlib.reload(sys.modules["app.db"])

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
# Import all models so they register with Base.metadata
from app.models import agent, api_key, graph, mcp_server, run, user  # noqa: E402, F401


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncSession:
    """
    Per-test session with SAVEPOINT-based isolation.

    The outer connection+transaction is rolled back at teardown. The session
    joins that transaction in 'create_savepoint' mode, so any commit() calls
    inside tests or router handlers only commit the savepoint — the outer
    rollback cleans up everything.
    """
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db_session) -> AsyncClient:
    """httpx client talking to the FastAPI app with the test session injected."""
    from app.main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.pop(get_db, None)
