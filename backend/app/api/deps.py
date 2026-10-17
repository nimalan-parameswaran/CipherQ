"""
CipherQ FastAPI Dependencies
Provides authenticated session resolution, CSRF validation, and DB session injection.
"""
import secrets
from datetime import datetime, timezone
from typing import Tuple
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from backend.app.core.config import settings
from backend.app.core.security import hash_session_token
from backend.app.db.session import get_db
from backend.app.db.models import User, Session


async def get_current_session_and_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Tuple[Session, User]:
    """
    Validates the session cookie against the database.
    Verifies that the session is not expired and the user is active.
    """
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: No session cookie present.",
            headers={"WWW-Authenticate": "Cookie"}
        )

    token_hash = hash_session_token(token)
    stmt = (
        select(Session)
        .options(selectinload(Session.user))
        .where(Session.token_hash == token_hash)
    )
    result = await db.execute(stmt)
    session_obj = result.scalar_one_or_none()

    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session: Token not recognized.",
            headers={"WWW-Authenticate": "Cookie"}
        )

    # Check expiration
    now = datetime.now(timezone.utc)
    # Ensure expires_at is timezone-aware
    expires_at = session_obj.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now:
        # Session expired: clean up from DB
        await db.delete(session_obj)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please log in again.",
            headers={"WWW-Authenticate": "Cookie"}
        )

    user = session_obj.user
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or disabled.",
            headers={"WWW-Authenticate": "Cookie"}
        )

    return session_obj, user


async def get_current_user(
    session_and_user: Tuple[Session, User] = Depends(get_current_session_and_user)
) -> User:
    """Dependency that returns the authenticated User model."""
    _, user = session_and_user
    return user


async def verify_csrf(
    request: Request,
    session_and_user: Tuple[Session, User] = Depends(get_current_session_and_user)
) -> None:
    """
    Verifies that the client provided a matching X-CSRF-Token header.
    Protects all mutating API requests (POST, PUT, PATCH, DELETE).
    """
    session_obj, _ = session_and_user
    csrf_header = request.headers.get("X-CSRF-Token")

    if not csrf_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF protection failed: Missing X-CSRF-Token header."
        )

    # Constant-time comparison to prevent timing side-channels
    if not secrets.compare_digest(csrf_header, session_obj.csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF protection failed: Invalid or mismatched CSRF token."
        )
