"""
Integration Tests for Authentication API & Session Security
Tests user registration, login, session cookies, CSRF protection,
session expiration, rate limiting, and secret leakage prevention.
"""
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.db.models import User, Session
from backend.app.core.config import settings


@pytest.mark.asyncio
async def test_credentialed_cors_allows_approved_pages_origin(client: AsyncClient):
    """Verify the deployed frontend origin can make credentialed API requests."""
    response = await client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "https://nimalan-parameswaran.github.io",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-CSRF-Token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://nimalan-parameswaran.github.io"
    )
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_credentialed_cors_rejects_unapproved_origin(client: AsyncClient):
    """Verify arbitrary origins cannot use the credentialed API."""
    response = await client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_register_user_success(client: AsyncClient, test_db_session: AsyncSession):
    """Verify user registration succeeds, sets defaults, and does not leak password hash."""
    payload = {
        "email": "user1@example.com",
        "password": "ValidStrongPassword123!",
        "plan_type": "FREE"
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["email"] == "user1@example.com"
    assert data["plan_type"] == "FREE"
    assert data["is_active"] is True
    assert "id" in data

    # Verify no secret leakage in response
    assert "password" not in data
    assert "hashed_password" not in data

    # Verify user exists in database and password is an Argon2id hash
    stmt = select(User).where(User.email == "user1@example.com")
    user = (await test_db_session.execute(stmt)).scalar_one_or_none()
    assert user is not None
    assert user.hashed_password.startswith("$argon2id$")
    assert user.hashed_password != payload["password"]


@pytest.mark.asyncio
async def test_register_duplicate_email_rejected(client: AsyncClient):
    """Verify registering the same email twice returns 409 Conflict."""
    payload = {
        "email": "duplicate@example.com",
        "password": "ValidStrongPassword123!",
        "plan_type": "FREE"
    }
    res1 = await client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = await client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_register_password_length_validation(client: AsyncClient):
    """Verify passwords under 10 characters are rejected with 422 Unprocessable Entity."""
    payload = {
        "email": "shortpwd@example.com",
        "password": "short",
        "plan_type": "FREE"
    }
    res = await client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_login_and_cookie_issuance(client: AsyncClient):
    """Verify login issues HttpOnly session cookie and returns a valid CSRF token."""
    # Register first
    email = "login_test@example.com"
    pwd = "LoginStrongPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})

    # Login
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    assert login_res.status_code == 200

    data = login_res.json()
    assert "csrf_token" in data
    assert len(data["csrf_token"]) >= 32
    assert data["user"]["email"] == email

    # Check session cookie headers
    cookies = login_res.cookies
    assert settings.SESSION_COOKIE_NAME in cookies
    cookie_header = login_res.headers.get("set-cookie", "")
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()


@pytest.mark.asyncio
async def test_cross_origin_login_issues_browser_compatible_cookie(client: AsyncClient):
    """Verify approved cross-origin login uses Secure SameSite=None cookies."""
    email = "cross_origin_login@example.com"
    pwd = "CrossOriginPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pwd},
        headers={"Origin": "https://nimalan-parameswaran.github.io"},
    )

    assert login_res.status_code == 200
    cookie_header = login_res.headers["set-cookie"].lower()
    assert "samesite=none" in cookie_header
    assert "secure" in cookie_header


@pytest.mark.asyncio
async def test_login_wrong_password_rejected(client: AsyncClient):
    """Verify incorrect password returns 401 Unauthorized."""
    email = "wrong_pwd_test@example.com"
    pwd = "CorrectPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})

    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword999!"})
    assert login_res.status_code == 401
    assert "Invalid email or password" in login_res.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limiting_on_login(client: AsyncClient):
    """Verify login rate limit triggers after exceeding allowed attempts."""
    email = "rate_limit_test@example.com"
    pwd = "ValidPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})

    # Execute 5 allowed login attempts
    for _ in range(settings.AUTH_RATE_LIMIT_LOGIN_MAX):
        await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})

    # 6th attempt should return 429 Too Many Requests
    blocked_res = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    assert blocked_res.status_code == 429
    assert "too many" in blocked_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_authenticated_me_and_session_expiry(client: AsyncClient, test_db_session: AsyncSession):
    """Verify /me profile access with cookie, and 401 after session expiration."""
    email = "expiry_test@example.com"
    pwd = "ValidPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    assert login_res.status_code == 200

    # Access /me with active session (cookie was set automatically by client on login)
    me_res = await client.get("/api/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["email"] == email

    # Access /me without cookie -> 401
    client.cookies.clear()
    unauth_res = await client.get("/api/v1/auth/me")
    assert unauth_res.status_code == 401

    # Login again to establish session
    login_res2 = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    assert login_res2.status_code == 200

    # Manually expire the session in database
    stmt = select(Session)
    session_records = (await test_db_session.execute(stmt)).scalars().all()
    for s in session_records:
        s.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await test_db_session.commit()

    # Access /me with expired session -> 401
    expired_res = await client.get("/api/v1/auth/me")
    assert expired_res.status_code == 401
    assert "expired" in expired_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_csrf_validation_and_logout(client: AsyncClient):
    """Verify CSRF token protection on mutating endpoints and successful logout."""
    email = "csrf_test@example.com"
    pwd = "ValidPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf_token = login_res.json()["csrf_token"]

    # 1. Attempt logout without CSRF header -> 403 Forbidden
    no_csrf_res = await client.post("/api/v1/auth/logout")
    assert no_csrf_res.status_code == 403
    assert "Missing X-CSRF-Token" in no_csrf_res.json()["detail"]

    # 2. Attempt logout with wrong CSRF header -> 403 Forbidden
    wrong_csrf_res = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": "invalid_fake_token_value"}
    )
    assert wrong_csrf_res.status_code == 403
    assert "Invalid or mismatched CSRF token" in wrong_csrf_res.json()["detail"]

    # 3. Attempt logout with valid CSRF header -> 200 OK
    valid_logout_res = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_token}
    )
    assert valid_logout_res.status_code == 200
    assert valid_logout_res.json()["status"] == "success"

    # 4. Verify session is revoked and subsequent requests fail
    after_logout_res = await client.get("/api/v1/auth/me")
    assert after_logout_res.status_code == 401


@pytest.mark.asyncio
async def test_user_isolation(client: AsyncClient):
    """Verify User A's session is isolated and cannot view User B's profile."""
    # Register and login User A
    await client.post("/api/v1/auth/register", json={"email": "usera@example.com", "password": "PasswordUserA123!"})
    login_a = await client.post("/api/v1/auth/login", json={"email": "usera@example.com", "password": "PasswordUserA123!"})
    cookie_a_val = login_a.cookies.get(settings.SESSION_COOKIE_NAME)

    # Register and login User B
    client.cookies.clear()
    await client.post("/api/v1/auth/register", json={"email": "userb@example.com", "password": "PasswordUserB123!"})
    login_b = await client.post("/api/v1/auth/login", json={"email": "userb@example.com", "password": "PasswordUserB123!"})
    cookie_b_val = login_b.cookies.get(settings.SESSION_COOKIE_NAME)

    # When client presents User A cookie, me returns User A
    client.cookies.set(settings.SESSION_COOKIE_NAME, cookie_a_val)
    me_a = await client.get("/api/v1/auth/me")
    assert me_a.json()["email"] == "usera@example.com"

    # When client presents User B cookie, me returns User B
    client.cookies.set(settings.SESSION_COOKIE_NAME, cookie_b_val)
    me_b = await client.get("/api/v1/auth/me")
    assert me_b.json()["email"] == "userb@example.com"


@pytest.mark.asyncio
async def test_no_secrets_leaked_in_responses(client: AsyncClient):
    """Verify password hashes, session hashes, and internal keys never appear in any API response."""
    email = "leak_audit@example.com"
    pwd = "UltraSecretPassword999!"
    reg_res = await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    me_res = await client.get("/api/v1/auth/me")
    usage_res = await client.get("/api/v1/auth/usage")

    for res in [reg_res, login_res, me_res, usage_res]:
        body_text = res.text
        assert pwd not in body_text
        assert "$argon2id$" not in body_text
        assert "hashed_password" not in body_text
        assert "token_hash" not in body_text
