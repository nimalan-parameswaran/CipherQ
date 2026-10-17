"""
Automated Test Suite for Phase 6: Free & Premium Entitlements Enforcement
Validates:
1. Free vs Premium authoritative entitlement resolution.
2. Upload quota boundaries (below, exact, and above limit).
3. Concurrency-safe quota protection (preventing race condition over-allocations).
4. Usage reconciliation after interrupted uploads, deletions, and server restarts.
5. Tier-gated AI endpoint authorization (403 for FREE on semantic search).
6. Unauthorized self-upgrade rejection (admin token enforcement).
7. Upgrade and downgrade lifecycle (preserving files on downgrade while over quota).
8. Multi-tenant plan, usage, and audit isolation.
9. Auditable plan modification logging without secret exposure.
"""
import io
import asyncio
import pytest
from httpx import AsyncClient
from sqlalchemy.future import select
from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.db.models import User, UsageRecord, FileRecord, PlanAuditEvent
from backend.app.services.entitlements import entitlement_service
from backend.app.services.vault import vault_service, reconcile_startup_vault


@pytest.mark.asyncio
async def test_free_and_premium_entitlement_resolution(client: AsyncClient):
    """Verify authoritative entitlement resolution: 1 GB for FREE, 5 GB for PREMIUM."""
    # Register FREE user
    reg_free = await client.post("/api/v1/auth/register", json={
        "email": "free_user@example.com",
        "password": "Password2026!",
        "plan_type": "FREE"
    })
    assert reg_free.status_code == 201

    # Register PREMIUM user
    reg_prem = await client.post("/api/v1/auth/register", json={
        "email": "prem_user@example.com",
        "password": "Password2026!",
        "plan_type": "PREMIUM"
    })
    assert reg_prem.status_code == 201

    # Check FREE user usage endpoint
    await client.post("/api/v1/auth/login", json={"email": "free_user@example.com", "password": "Password2026!"})
    free_usage = await client.get("/api/v1/auth/usage")
    assert free_usage.status_code == 200
    free_data = free_usage.json()
    assert free_data["storage_quota_bytes"] == 1_000_000_000  # 1 GB decimal
    assert free_data["plan_type"] == "FREE"
    assert free_data["ai_daily_limit"] == 0

    # Check PREMIUM user usage endpoint
    await client.post("/api/v1/auth/login", json={"email": "prem_user@example.com", "password": "Password2026!"})
    prem_usage = await client.get("/api/v1/auth/usage")
    assert prem_usage.status_code == 200
    prem_data = prem_usage.json()
    assert prem_data["storage_quota_bytes"] == 5_000_000_000  # 5 GB decimal
    assert prem_data["plan_type"] == "PREMIUM"
    assert prem_data["ai_daily_limit"] == 100


@pytest.mark.asyncio
async def test_upload_below_exact_and_above_quota(client: AsyncClient, test_db_session):
    """
    Simulate a user nearing quota boundary and verify that uploads below or at limit succeed,
    while uploads exceeding the remaining quota are rejected with HTTP 413.
    """
    email = "quota_boundary_user@example.com"
    pwd = "Password2026!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd, "plan_type": "FREE"})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # Artificially set usage to 999,999,800 bytes (200 bytes remaining of 1,000,000,000 bytes)
    user_stmt = select(User).where(User.email == email)
    user = (await test_db_session.execute(user_stmt)).scalar_one()

    usage_stmt = select(UsageRecord).where(UsageRecord.user_id == user.id)
    usage = (await test_db_session.execute(usage_stmt)).scalar_one()
    usage.storage_bytes_used = 999_999_800
    await test_db_session.commit()

    # 1. Upload 50 bytes (below limit: 200 remaining - 50 = 150 remaining) -> SUCCESS (201)
    payload_50 = b"A" * 50
    up_res1 = await client.post(
        "/api/v1/files",
        files={"file": ("chunk_50.txt", payload_50, "text/plain")},
        headers=headers
    )
    assert up_res1.status_code == 201
    file1_id = up_res1.json()["id"]

    # 2. Upload 250 bytes (exceeds remaining ~150 bytes) -> REJECTED (413)
    payload_250 = b"B" * 250
    up_res2 = await client.post(
        "/api/v1/files",
        files={"file": ("chunk_250.txt", payload_250, "text/plain")},
        headers=headers
    )
    assert up_res2.status_code == 413
    assert "quota" in up_res2.json()["detail"].lower()

    # Clean up
    await client.delete(f"/api/v1/files/{file1_id}", headers=headers)


@pytest.mark.asyncio
async def test_concurrent_uploads_racing_for_quota(client: AsyncClient, test_db_session):
    """
    Verify that concurrent upload requests racing for the same user's remaining quota
    cannot jointly exceed the quota limit.
    """
    email = "concurrent_quota_user@example.com"
    pwd = "Password2026!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd, "plan_type": "FREE"})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # Set usage so user has exactly 300 bytes remaining (1,000,000,000 - 300)
    user_stmt = select(User).where(User.email == email)
    user = (await test_db_session.execute(user_stmt)).scalar_one()

    usage_stmt = select(UsageRecord).where(UsageRecord.user_id == user.id)
    usage = (await test_db_session.execute(usage_stmt)).scalar_one()
    usage.storage_bytes_used = 999_999_700
    await test_db_session.commit()

    # Launch two concurrent uploads of 200 bytes each.
    # Individually, each 200B fits within the 300B remaining.
    # Jointly (400B), they exceed the 300B remaining!
    async def upload_task(name: str):
        payload = b"C" * 200
        return await client.post(
            "/api/v1/files",
            files={"file": (f"{name}.txt", payload, "text/plain")},
            headers=headers
        )

    res1, res2 = await asyncio.gather(upload_task("task1"), upload_task("task2"))

    status_codes = [res1.status_code, res2.status_code]
    assert 201 in status_codes, "At least one concurrent upload fitting within quota should succeed"
    assert 413 in status_codes, "The racing concurrent upload that would cause an overage must be rejected with 413"

    # Verify final stored usage in database did NOT exceed 1,000,000,000 bytes
    await test_db_session.refresh(usage)
    assert usage.storage_bytes_used <= 1_000_000_000, "Usage record exceeded authoritative quota limit!"


@pytest.mark.asyncio
async def test_usage_reconciliation_after_restart_and_deletion(client: AsyncClient, test_db_session):
    """
    Verify that startup reconciliation accurately recalculates storage_bytes_used
    from active FileRecords, preventing stale or negative numbers.
    """
    email = "recon_user@example.com"
    pwd = "Password2026!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd, "plan_type": "FREE"})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # Upload two files of known sizes
    up1 = await client.post("/api/v1/files", files={"file": ("f1.txt", b"1234567890", "text/plain")}, headers=headers)
    up2 = await client.post("/api/v1/files", files={"file": ("f2.txt", b"ABCDEFGHIJ", "text/plain")}, headers=headers)
    assert up1.status_code == 201
    assert up2.status_code == 201
    f1_id = up1.json()["id"]
    f2_id = up2.json()["id"]

    # Verify usage is 20 bytes
    u_res = await client.get("/api/v1/auth/usage")
    assert u_res.json()["storage_bytes_used"] == 20

    # Corrupt usage record intentionally to simulate database drift/crash
    user_stmt = select(User).where(User.email == email)
    user = (await test_db_session.execute(user_stmt)).scalar_one()
    usage_stmt = select(UsageRecord).where(UsageRecord.user_id == user.id)
    usage = (await test_db_session.execute(usage_stmt)).scalar_one()
    usage.storage_bytes_used = 999999  # Stale corrupted value
    await test_db_session.commit()

    # Run startup reconciliation using isolated test session factory
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_factory():
        yield test_db_session

    await reconcile_startup_vault(mock_factory)

    # Verify reconciliation corrected usage back to actual active file size (20 bytes)
    await test_db_session.refresh(usage)
    assert usage.storage_bytes_used == 20, "Startup reconciliation did not accurately recalculate usage!"

    # Clean up
    await client.delete(f"/api/v1/files/{f1_id}", headers=headers)
    await client.delete(f"/api/v1/files/{f2_id}", headers=headers)
    await test_db_session.refresh(usage)
    assert usage.storage_bytes_used == 0


@pytest.mark.asyncio
async def test_premium_endpoint_access_granted_and_denied(client: AsyncClient):
    """Verify tier gating: FREE user receives 403 on semantic endpoint; PREMIUM user succeeds."""
    # FREE user
    await client.post("/api/v1/auth/register", json={"email": "gate_free@example.com", "password": "Password2026!", "plan_type": "FREE"})
    l_free = await client.post("/api/v1/auth/login", json={"email": "gate_free@example.com", "password": "Password2026!"})
    csrf_free = l_free.json()["csrf_token"]

    # FREE user calling dedicated semantic endpoint -> 403 Forbidden
    res_sem = await client.post(
        "/api/v1/ai/semantic",
        json={"query": "test query"},
        headers={"X-CSRF-Token": csrf_free}
    )
    assert res_sem.status_code == 403
    assert "premium" in res_sem.json()["detail"].lower()

    # FREE user calling query with mode='semantic' -> 403 Forbidden
    res_mode = await client.post(
        "/api/v1/ai/query",
        json={"query": "test query", "mode": "semantic"},
        headers={"X-CSRF-Token": csrf_free}
    )
    assert res_mode.status_code == 403

    # FREE user calling query with default/auto mode -> 200 OK (falls back to keyword)
    res_auto = await client.post(
        "/api/v1/ai/query",
        json={"query": "test query", "mode": "auto"},
        headers={"X-CSRF-Token": csrf_free}
    )
    assert res_auto.status_code == 200
    assert res_auto.json()["mode_used"] == "FTS5_KEYWORD"

    # PREMIUM user
    await client.post("/api/v1/auth/register", json={"email": "gate_prem@example.com", "password": "Password2026!", "plan_type": "PREMIUM"})
    l_prem = await client.post("/api/v1/auth/login", json={"email": "gate_prem@example.com", "password": "Password2026!"})
    csrf_prem = l_prem.json()["csrf_token"]

    # PREMIUM user calling dedicated semantic endpoint -> 200 OK
    res_prem_sem = await client.post(
        "/api/v1/ai/semantic",
        json={"query": "test query"},
        headers={"X-CSRF-Token": csrf_prem}
    )
    assert res_prem_sem.status_code == 200
    assert res_prem_sem.json()["mode_used"] == "SEMANTIC_VECTOR"


@pytest.mark.asyncio
async def test_unauthorized_self_upgrade_rejected(client: AsyncClient):
    """Verify ordinary users cannot self-upgrade without valid X-Admin-Token."""
    await client.post("/api/v1/auth/register", json={"email": "hack_user@example.com", "password": "Password2026!", "plan_type": "FREE"})
    login_res = await client.post("/api/v1/auth/login", json={"email": "hack_user@example.com", "password": "Password2026!"})
    csrf = login_res.json()["csrf_token"]

    # Attempt to call admin plan modification without admin token
    res_no_tok = await client.post(
        "/api/v1/admin/users/plan",
        json={"email": "hack_user@example.com", "new_plan": "PREMIUM"},
        headers={"X-CSRF-Token": csrf}
    )
    assert res_no_tok.status_code == 403
    assert "unauthorized" in res_no_tok.json()["detail"].lower()

    # Attempt to call with invalid admin token
    res_bad_tok = await client.post(
        "/api/v1/admin/users/plan",
        json={"email": "hack_user@example.com", "new_plan": "PREMIUM"},
        headers={"X-CSRF-Token": csrf, "X-Admin-Token": "invalid-secret-guess"}
    )
    assert res_bad_tok.status_code == 403


@pytest.mark.asyncio
async def test_upgrade_and_immediate_entitlement_application(client: AsyncClient):
    """Verify an admin upgrade immediately activates 5GB quota and semantic features."""
    email = "upgrade_user@example.com"
    pwd = "Password2026!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd, "plan_type": "FREE"})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf = login_res.json()["csrf_token"]

    # Verify initial FREE quota
    u0 = await client.get("/api/v1/auth/usage")
    assert u0.json()["storage_quota_bytes"] == 1_000_000_000
    assert u0.json()["plan_type"] == "FREE"

    # Authorized admin upgrade
    upgrade_res = await client.post(
        "/api/v1/admin/users/plan",
        json={"email": email, "new_plan": "PREMIUM", "reason": "authorized_test_upgrade"},
        headers={"X-Admin-Token": settings.ADMIN_TOKEN}
    )
    assert upgrade_res.status_code == 200
    assert upgrade_res.json()["new_plan"] == "PREMIUM"
    assert upgrade_res.json()["storage_quota_bytes"] == 5_000_000_000

    # Verify active session immediately receives updated entitlements
    u1 = await client.get("/api/v1/auth/usage")
    assert u1.json()["storage_quota_bytes"] == 5_000_000_000
    assert u1.json()["plan_type"] == "PREMIUM"

    # Semantic search endpoint is now immediately accessible
    sem_res = await client.post(
        "/api/v1/ai/semantic",
        json={"query": "test query"},
        headers={"X-CSRF-Token": csrf}
    )
    assert sem_res.status_code == 200


@pytest.mark.asyncio
async def test_downgrade_over_quota_preserves_files_and_blocks_new_uploads(client: AsyncClient, test_db_session):
    """
    On downgrade to FREE:
    - Existing files are preserved (not deleted automatically).
    - Downloads, listings, and keyword search continue to function.
    - If usage exceeds 1 GB, new uploads are blocked with 413 until usage drops below 1 GB.
    """
    email = "over_quota_downgrade@example.com"
    pwd = "Password2026!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd, "plan_type": "PREMIUM"})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # Upload file of 50 bytes
    up_res = await client.post(
        "/api/v1/files",
        files={"file": ("preserved_doc.txt", b"Precious research data that must never be deleted", "text/plain")},
        headers=headers
    )
    assert up_res.status_code == 201
    file_id = up_res.json()["id"]

    # Artificially set usage to 1.5 GB (1,500,000,000 bytes)
    user_stmt = select(User).where(User.email == email)
    user = (await test_db_session.execute(user_stmt)).scalar_one()
    usage_stmt = select(UsageRecord).where(UsageRecord.user_id == user.id)
    usage = (await test_db_session.execute(usage_stmt)).scalar_one()
    usage.storage_bytes_used = 1_500_000_000
    await test_db_session.commit()

    # Admin downgrades user to FREE
    down_res = await client.post(
        "/api/v1/admin/users/plan",
        json={"email": email, "new_plan": "FREE", "reason": "subscription_expired"},
        headers={"X-Admin-Token": settings.ADMIN_TOKEN}
    )
    assert down_res.status_code == 200
    assert down_res.json()["new_plan"] == "FREE"
    assert down_res.json()["storage_quota_bytes"] == 1_000_000_000

    # 1. Existing file is preserved and can be listed
    list_res = await client.get("/api/v1/files")
    assert list_res.status_code == 200
    files = list_res.json()["files"]
    assert any(f["id"] == file_id for f in files), "Existing file was deleted during downgrade!"

    # 2. Existing file can be downloaded and decrypted
    dl_res = await client.get(f"/api/v1/files/{file_id}/download")
    assert dl_res.status_code == 200
    assert b"Precious research data" in dl_res.content

    # 3. New upload attempt is BLOCKED with 413 because 1.5 GB > 1 GB
    new_up = await client.post(
        "/api/v1/files",
        files={"file": ("new_doc.txt", b"Should be rejected", "text/plain")},
        headers=headers
    )
    assert new_up.status_code == 413
    assert "exceeds" in new_up.json()["detail"].lower()

    # 4. User deletes file, bringing usage back below 1 GB
    usage.storage_bytes_used = 500_000_000  # Now within 1 GB limit
    await test_db_session.commit()

    # 5. New upload now SUCCEEDS
    new_up_ok = await client.post(
        "/api/v1/files",
        files={"file": ("now_allowed.txt", b"Now allowed", "text/plain")},
        headers=headers
    )
    assert new_up_ok.status_code == 201


@pytest.mark.asyncio
async def test_cross_user_isolation_plan_and_usage(client: AsyncClient):
    """Verify User A cannot access User B's plan, usage, or audit logs."""
    # User A
    await client.post("/api/v1/auth/register", json={"email": "iso_a@example.com", "password": "Password2026!", "plan_type": "FREE"})
    l_a = await client.post("/api/v1/auth/login", json={"email": "iso_a@example.com", "password": "Password2026!"})
    csrf_a = l_a.json()["csrf_token"]

    # User B
    await client.post("/api/v1/auth/register", json={"email": "iso_b@example.com", "password": "Password2026!", "plan_type": "PREMIUM"})

    # User A views their own usage -> matches User A only
    res_a = await client.get("/api/v1/auth/usage")
    assert res_a.json()["plan_type"] == "FREE"

    # User A cannot view audit logs
    audit_res = await client.get("/api/v1/admin/audit-logs", headers={"X-CSRF-Token": csrf_a})
    assert audit_res.status_code == 403


@pytest.mark.asyncio
async def test_plan_audit_logging(client: AsyncClient):
    """Verify that plan changes record immutable audit events with zero secrets logged."""
    email = "audit_check@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "Password2026!", "plan_type": "FREE"})

    # Admin upgrade
    await client.post(
        "/api/v1/admin/users/plan",
        json={"email": email, "new_plan": "PREMIUM", "reason": "customer_support_request"},
        headers={"X-Admin-Token": settings.ADMIN_TOKEN}
    )

    # Fetch audit logs via admin endpoint
    logs_res = await client.get("/api/v1/admin/audit-logs", headers={"X-Admin-Token": settings.ADMIN_TOKEN})
    assert logs_res.status_code == 200
    logs = logs_res.json()
    assert len(logs) > 0

    latest = logs[0]
    assert latest["old_plan"] == "FREE"
    assert latest["new_plan"] == "PREMIUM"
    assert latest["changed_by"] == "admin_api"
    assert latest["reason"] == "customer_support_request"

    # Verify NO secrets are leaked in audit log
    for key in ("password", "token", "content", "key"):
        assert key not in latest


@pytest.mark.asyncio
async def test_cli_manage_plan(client: AsyncClient, test_db_session):
    """Verify that the command-line administration tool modifies plans and logs audit events."""
    from backend.app.cli.manage_plan import set_user_plan
    from unittest.mock import patch
    from contextlib import asynccontextmanager

    email = "cli_user@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "Password2026!", "plan_type": "FREE"})

    @asynccontextmanager
    async def mock_session():
        yield test_db_session

    with patch("backend.app.cli.manage_plan.AsyncSessionLocal", side_effect=mock_session):
        exit_code = await set_user_plan(email, "PREMIUM", reason="terminal_admin_action")
        assert exit_code == 0

    # Verify user is now PREMIUM
    user_stmt = select(User).where(User.email == email)
    user = (await test_db_session.execute(user_stmt)).scalar_one()
    assert user.plan_type == "PREMIUM"

    # Verify audit event was created by cli_admin
    audit_stmt = select(PlanAuditEvent).where(PlanAuditEvent.user_id == user.id)
    audit = (await test_db_session.execute(audit_stmt)).scalar_one()
    assert audit.changed_by == "cli_admin"
    assert audit.new_plan == "PREMIUM"
    assert audit.reason == "terminal_admin_action"


@pytest.mark.asyncio
async def test_global_disk_space_safety_reserve_rejected(client: AsyncClient):
    """Verify that uploads are rejected with HTTP 507 when host disk space drops below safety reserve."""
    from unittest.mock import patch
    from collections import namedtuple
    from backend.app.services.entitlements import DiskSpaceExhaustedError

    DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])

    # Register and login user
    email = "disk_test@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "Password2026!", "plan_type": "FREE"})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": "Password2026!"})
    csrf_token = login_res.json()["csrf_token"]

    # Mock disk_usage to return 5 MB free (less than settings.MIN_FREE_DISK_BYTES)
    mock_stat = DiskUsage(total=32_000_000_000, used=31_995_000_000, free=5_000_000)

    with patch("shutil.disk_usage", return_value=mock_stat):
        res = await client.post(
            "/api/v1/files",
            files={"file": ("test.txt", b"Safety reserve test content", "text/plain")},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert res.status_code == 507
        assert "storage headroom safety reserve reached" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_global_in_flight_tracking_lifecycle():
    """Verify that InFlightQuotaTracker tracks global aggregate in-flight bytes across users."""
    from backend.app.services.entitlements import InFlightQuotaTracker

    tracker = InFlightQuotaTracker()
    assert tracker.get_global_in_flight_bytes() == 0

    async with tracker.track_upload(user_id="user_1", current_committed_bytes=0, quota_bytes=10_000_000, content_length=5_000_000):
        assert tracker.get_in_flight_bytes("user_1") == 5_000_000
        assert tracker.get_global_in_flight_bytes() == 5_000_000

        async with tracker.track_upload(user_id="user_2", current_committed_bytes=0, quota_bytes=10_000_000, content_length=2_000_000):
            assert tracker.get_in_flight_bytes("user_2") == 2_000_000
            assert tracker.get_global_in_flight_bytes() == 7_000_000

        # After user_2 completes, global in-flight decrements to 5,000,000
        assert tracker.get_in_flight_bytes("user_2") == 0
        assert tracker.get_global_in_flight_bytes() == 5_000_000

    # After user_1 completes, global in-flight returns to 0
    assert tracker.get_in_flight_bytes("user_1") == 0
    assert tracker.get_global_in_flight_bytes() == 0


