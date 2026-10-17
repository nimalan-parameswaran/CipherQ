"""
Pytest Fixtures for CipherQ Test Suite
Uses temporary directories and isolated SQLite database for repeatable, hermetic tests.
"""
import pytest
import pytest_asyncio
import tempfile
from pathlib import Path
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event

from backend.app.core.config import settings
from backend.app.core.key_manager import MasterKeyManager
from backend.app.db.session import Base, get_db
from backend.app.core.security import rate_limiter
from backend.app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the in-memory rate limiter before each test."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def temp_dir():
    """Provide an isolated temporary directory for test storage and keys."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def test_key_manager(temp_dir):
    """Provide an isolated MasterKeyManager using the temporary directory."""
    key_path = temp_dir / ".vault_master_test.key"
    mgr = MasterKeyManager(key_path=key_path)
    mgr.generate_master_key()
    return mgr


@pytest_asyncio.fixture
async def test_db_session(temp_dir) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated test database session backed by a temporary SQLite file."""
    db_file = temp_dir / "test_cipherq.db"
    test_db_url = f"sqlite+aiosqlite:///{db_file}"

    test_engine = create_async_engine(
        test_db_url,
        echo=False,
        connect_args={"check_same_thread": False}
    )

    @event.listens_for(test_engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async_session = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False
    )

    # Initialize tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    await test_engine.dispose()


@pytest_asyncio.fixture
async def client(test_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient configured to use the test database session."""
    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
