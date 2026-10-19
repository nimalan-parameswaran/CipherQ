"""
CipherQ Authentication API Endpoints
Provides registration, login with secure cookie handling, logout, and profile queries.
Enforces rate limiting, Argon2id verification, and CSRF token emission.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.core.config import settings
from backend.app.core.security import (
    hash_password,
    verify_password,
    generate_session_token,
    hash_session_token,
    generate_csrf_token,
    rate_limiter
)
from backend.app.db.session import get_db
from backend.app.db.models import User, Session, UsageRecord
from backend.app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
    SessionResponse,
    MessageResponse,
    UsageResponse
)
from backend.app.api.deps import get_current_user, get_current_session_and_user, verify_csrf
from backend.app.services.entitlements import entitlement_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def get_client_ip(request: Request) -> str:
    """Safely resolve client IP for rate limiting."""
    if request.client:
        return request.client.host
    return "127.0.0.1"


def get_session_cookie_options(request: Request) -> tuple[str, bool, bool]:
    """
    Return cookie attributes appropriate for the current browser request.

    Local same-origin development keeps the configured Lax/non-secure defaults.
    When the approved frontend is hosted on another origin, browsers require a
    Secure, SameSite=None cookie before they will send the session back to the
    API.
    """
    same_site = settings.COOKIE_SAMESITE
    secure = settings.COOKIE_SECURE
    partitioned = False
    origin = request.headers.get("origin", "").rstrip("/")
    request_origin = str(request.base_url).rstrip("/")

    allowed_origins = {
        configured_origin.strip().rstrip("/")
        for configured_origin in settings.CORS_ALLOWED_ORIGINS.split(",")
        if configured_origin.strip()
    }
    if origin in allowed_origins and origin != request_origin:
        same_site = "none"
        secure = True
        partitioned = True

    return same_site, secure, partitioned


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user account with Argon2id password hashing and quota initialization."""
    client_ip = get_client_ip(request)
    if not rate_limiter.is_allowed(
        client_ip,
        action="register",
        max_requests=settings.AUTH_RATE_LIMIT_REGISTER_MAX,
        window_seconds=settings.AUTH_RATE_LIMIT_REGISTER_WINDOW_SEC
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Registration rate limit exceeded. Please wait a minute before trying again."
        )

    # Check if email is already taken
    stmt = select(User).where(User.email == payload.email)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists."
        )

    # Hash password with Argon2id
    hashed_pwd = hash_password(payload.password)

    user = User(
        email=payload.email,
        hashed_password=hashed_pwd,
        plan_type=payload.plan_type,
        is_active=1
    )
    db.add(user)
    await db.flush()  # Populates user.id

    # Initialize usage record
    usage = UsageRecord(
        user_id=user.id,
        storage_bytes_used=0,
        ai_queries_today=0,
        last_query_date=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    db.add(usage)
    await db.commit()
    await db.refresh(user)

    return user


@router.post("/login", response_model=SessionResponse)
async def login_user(
    payload: UserLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate credentials, issue an HttpOnly session cookie, and return a CSRF token."""
    client_ip = get_client_ip(request)
    if not rate_limiter.is_allowed(
        client_ip,
        action="login",
        max_requests=settings.AUTH_RATE_LIMIT_LOGIN_MAX,
        window_seconds=settings.AUTH_RATE_LIMIT_LOGIN_WINDOW_SEC
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please wait a minute before trying again."
        )

    # Find user by email
    stmt = select(User).where(User.email == payload.email)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Cookie"}
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been suspended or deactivated."
        )

    # Generate high-entropy session and CSRF tokens
    raw_session_token = generate_session_token()
    token_hash = hash_session_token(raw_session_token)
    csrf_token = generate_csrf_token()

    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.SESSION_EXPIRE_HOURS)

    # Store hashed session in DB
    session_record = Session(
        token_hash=token_hash,
        user_id=user.id,
        csrf_token=csrf_token,
        expires_at=expires_at
    )
    db.add(session_record)
    await db.commit()

    cookie_samesite, cookie_secure, cookie_partitioned = get_session_cookie_options(request)

    # Set secure HttpOnly cookie
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_session_token,
        max_age=settings.SESSION_EXPIRE_HOURS * 3600,
        httponly=True,
        samesite=cookie_samesite,
        secure=cookie_secure,
        partitioned=cookie_partitioned,
        path="/"
    )

    return SessionResponse(
        user=UserResponse.model_validate(user),
        csrf_token=csrf_token,
        expires_at=expires_at,
        # Cross-origin static frontends may block third-party cookies. The
        # frontend keeps this token only in sessionStorage for the current tab.
        session_token=raw_session_token
    )


@router.post("/logout", response_model=MessageResponse)
async def logout_user(
    request: Request,
    response: Response,
    session_and_user=Depends(get_current_session_and_user),
    _csrf=Depends(verify_csrf),
    db: AsyncSession = Depends(get_db)
):
    """Revoke session record in database and clear the session cookie."""
    session_obj, _ = session_and_user
    await db.delete(session_obj)
    await db.commit()

    cookie_samesite, cookie_secure, cookie_partitioned = get_session_cookie_options(request)
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        samesite=cookie_samesite,
        secure=cookie_secure,
        partitioned=cookie_partitioned
    )

    return MessageResponse(message="Successfully logged out.")


@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    response: Response,
    session_and_user=Depends(get_current_session_and_user)
):
    """Return the profile of the currently authenticated user (no secrets) and active CSRF token."""
    response.headers["Cache-Control"] = "no-store"
    session_obj, user = session_and_user
    user_resp = UserResponse.model_validate(user)
    user_resp.csrf_token = session_obj.csrf_token
    return user_resp


@router.get("/usage", response_model=UsageResponse)
async def get_my_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Return storage utilization and plan quota for the current user."""
    stmt = select(UsageRecord).where(UsageRecord.user_id == current_user.id)
    usage = (await db.execute(stmt)).scalar_one_or_none()

    storage_used = usage.storage_bytes_used if usage else 0
    ai_queries = usage.ai_queries_today if usage else 0

    quota = entitlement_service.get_user_quota(current_user)
    entitlements = entitlement_service.get_user_entitlements(current_user)
    ai_limit = entitlements["ai_daily_limit"]

    return UsageResponse(
        storage_bytes_used=storage_used,
        storage_quota_bytes=quota,
        ai_queries_today=ai_queries,
        ai_daily_limit=ai_limit,
        plan_type=current_user.plan_type
    )
