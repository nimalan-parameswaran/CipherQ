"""
CipherQ FastAPI Application Entry Point
Mounts API endpoints and static vanilla frontend under the same origin.
Enforces Master Key startup self-test during application lifespan.
"""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.core.config import settings
from backend.app.core.key_manager import key_manager
from backend.app.db.session import engine, Base, AsyncSessionLocal
from backend.app.services.vault import reconcile_startup_vault
from backend.app.api.auth import router as auth_router
from backend.app.api.files import router as files_router

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown hooks.
    Ensures storage directories exist, database schema is created,
    Master Key passes its self-test, and vault reconciliation executes.
    """
    # 1. Initialize local storage directories
    settings.init_directories()

    # 2. Initialize database schema
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
