"""
CipherQ FastAPI Application Entry Point
Mounts API endpoints and static vanilla frontend under the same origin.
Enforces Master Key startup self-test during application lifespan.
"""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text
from backend.app.core.config import settings
from backend.app.core.key_manager import key_manager
from backend.app.db.session import engine, Base, AsyncSessionLocal
from backend.app.services.vault import reconcile_startup_vault
from backend.app.api.auth import router as auth_router
from backend.app.api.files import router as files_router
from backend.app.api.ai import router as ai_router
from backend.app.api.admin import router as admin_router

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown hooks.
    Ensures storage directories exist, database schema is created,
    Master Key passes its self-test, and vault reconciliation executes.
    """
    # 0. Production Security Sanity Check
    if settings.ENVIRONMENT.lower() == "production":
        if settings.ADMIN_TOKEN == "cipherq-dev-admin-secret-2026":
            raise RuntimeError(
                "FATAL SECURITY CONFIGURATION: Running in production mode with default development ADMIN_TOKEN! "
                "Configure a secure 256-bit ADMIN_TOKEN in /etc/cipherq/cipherq.env or environment."
            )

    # 1. Initialize local storage directories
    settings.init_directories()

    # 2. Initialize database schema & SQLite FTS5 table
    async with engine.begin() as conn:
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

    # 3. Master Key startup self-test
    key_manager.validate_or_init()

    # 4. Conservative startup vault reconciliation
    await reconcile_startup_vault(AsyncSessionLocal)

    yield

    # Shutdown logic
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Your Private Cloud. Your Personal AI.",
    lifespan=lifespan
)

# Register API v1 Routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(files_router, prefix=settings.API_V1_STR)
app.include_router(ai_router, prefix=settings.API_V1_STR)
app.include_router(admin_router, prefix=settings.API_V1_STR)


@app.get(f"{settings.API_V1_STR}/health", tags=["Health"])
async def health_check():
    """System health check endpoint."""
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "master_key_configured": settings.MASTER_KEY_PATH.exists()
    }


# Mount the static vanilla frontend at root for same-origin serving
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
