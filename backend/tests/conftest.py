"""
Pytest Fixtures for CipherQ Test Suite
Uses temporary directories and isolated SQLite database for repeatable, hermetic tests.
"""

import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from backend.app.core.config import settings
from backend.app.core.key_manager import MasterKeyManager, key_manager
from backend.app.core.security import rate_limiter
from backend.app.db.session import Base, get_db
from backend.app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the in-memory rate limiter before and after each test."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture(autouse=True)
def configure_test_disk_safety():
    """Use a small disk safety reserve during tests."""
    original_value = settings.MIN_FREE_DISK_BYTES
    settings.MIN_FREE_DISK_BYTES = 10_485_760  # 10 MB
    yield
    settings.MIN_FREE_DISK_BYTES = original_value


@pytest.fixture
def temp_dir():
    """Provide an isolated temporary directory for test storage and keys."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def test_key_manager(temp_dir):
    """Provide an isolated MasterKeyManager for unit tests."""
    key_path = temp_dir / ".vault_master_test.key"
    manager = MasterKeyManager(key_path=key_path)
    manager.generate_master_key()
    return manager


@pytest.fixture(autouse=True)
def configure_test_master_key(temp_dir):
    """Keep the global application key isolated inside the test directory."""
    original_settings_path = settings.MASTER_KEY_PATH
    original_manager_path = key_manager.key_path

    test_key_path = temp_dir / ".vault_master_app_test.key"

    settings.MASTER_KEY_PATH = test_key_path
    key_manager.key_path = test_key_path

    try:
        key_manager.generate_master_key()
        yield
    finally:
        key_manager.key_path = original_manager_path
        settings.MASTER_KEY_PATH = original_settings_path


@pytest_asyncio.fixture
async def test_db_session(temp_dir) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated test database session."""
    db_file = temp_dir / "test_cipherq.db"
    test_db_url = f"sqlite+aiosqlite:///{db_file}"

    test_engine = create_async_engine(
        test_db_url,
        echo=False,
        connect_args={"check_same_thread": False},
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
        autoflush=False,
        autocommit=False,
    )

    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks_fts USING fts5(
                        chunk_id UNINDEXED,
                        file_id UNINDEXED,
                        user_id UNINDEXED,
                        content
                    );
                    """
                )
            )

        async with async_session() as session:
            yield session
    finally:
        await test_engine.dispose()


@pytest_asyncio.fixture
async def client(
    test_db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient using the isolated test database."""

    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            yield async_client
    finally:
        app.dependency_overrides.pop(get_db, None)
