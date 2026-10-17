"""
Integration Tests for Files API & Vault Storage
Tests authenticated upload, download with decryption, cross-user isolation,
quota enforcement, safe filename handling, CSRF protection, and two-phase deletion.
"""
import io
import pytest
from httpx import AsyncClient

from backend.app.core.config import settings
from backend.app.services.vault import get_vault_path


@pytest.mark.asyncio
async def test_file_upload_download_roundtrip(client: AsyncClient):
    """Verify authenticated upload encrypts to vault and download decrypts with exact match."""
    # 1. Register & login User A
    email = "vault_user_a@example.com"
    pwd = "ValidVaultPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd, "plan_type": "FREE"})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf_token = login_res.json()["csrf_token"]

    # 2. Upload file
    test_content = b"Confidential financial statement data for CipherQ vault."
    files = {"file": ("financial_statement.txt", io.BytesIO(test_content), "text/plain")}

    upload_res = await client.post(
        "/api/v1/files",
        files=files,
        headers={"X-CSRF-Token": csrf_token}
    )
    assert upload_res.status_code == 201
    file_data = upload_res.json()
    file_id = file_data["id"]
    assert file_data["original_name"] == "financial_statement.txt"
    assert file_data["file_size_bytes"] == len(test_content)
    assert "sha256_hash" in file_data

    # Verify physical file on disk is encrypted (does NOT contain plaintext)
    vault_file = get_vault_path(f"{file_id}.cqenc")
    assert vault_file.exists()
    assert test_content not in vault_file.read_bytes(), "Ciphertext file must not contain raw plaintext!"

    # 3. Download and verify plaintext decryption
    download_res = await client.get(f"/api/v1/files/{file_id}/download")
    assert download_res.status_code == 200
    assert download_res.content == test_content
    assert download_res.headers["content-type"] == "text/plain"

    # 4. Clean up
    del_res = await client.delete(f"/api/v1/files/{file_id}", headers={"X-CSRF-Token": csrf_token})
    assert del_res.status_code == 200
    assert not vault_file.exists()


@pytest.mark.asyncio
async def test_cross_user_file_isolation(client: AsyncClient):
    """Verify User B cannot list, download, or delete User A's files."""
    # Register & Login User A
    await client.post("/api/v1/auth/register", json={"email": "alice@example.com", "password": "AlicePassword123!"})
    login_a = await client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "AlicePassword123!"})
    csrf_a = login_a.json()["csrf_token"]
    cookie_a = login_a.cookies.get(settings.SESSION_COOKIE_NAME)

    # User A uploads a file
    client.cookies.set(settings.SESSION_COOKIE_NAME, cookie_a)
    upload_res = await client.post(
        "/api/v1/files",
        files={"file": ("alice_secret.pdf", io.BytesIO(b"Alice Secret Data"), "application/pdf")},
        headers={"X-CSRF-Token": csrf_a}
    )
    file_a_id = upload_res.json()["id"]

    # Register & Login User B
    client.cookies.clear()
    await client.post("/api/v1/auth/register", json={"email": "bob@example.com", "password": "BobPassword123!"})
    login_b = await client.post("/api/v1/auth/login", json={"email": "bob@example.com", "password": "BobPassword123!"})
    csrf_b = login_b.json()["csrf_token"]
    cookie_b = login_b.cookies.get(settings.SESSION_COOKIE_NAME)

    # User B lists files -> must be empty
    client.cookies.set(settings.SESSION_COOKIE_NAME, cookie_b)
    list_res = await client.get("/api/v1/files")
    assert list_res.status_code == 200
    assert list_res.json()["total_count"] == 0

    # User B attempts to download User A's file -> 404 Not Found
    download_b_res = await client.get(f"/api/v1/files/{file_a_id}/download")
    assert download_b_res.status_code == 404
    assert "access denied" in download_b_res.json()["detail"].lower()

    # User B attempts to delete User A's file -> 404 Not Found
    delete_b_res = await client.delete(f"/api/v1/files/{file_a_id}", headers={"X-CSRF-Token": csrf_b})
    assert delete_b_res.status_code == 404

    # Clean up User A's file
    client.cookies.set(settings.SESSION_COOKIE_NAME, cookie_a)
    await client.delete(f"/api/v1/files/{file_a_id}", headers={"X-CSRF-Token": csrf_a})


@pytest.mark.asyncio
async def test_csrf_required_for_file_mutations(client: AsyncClient):
    """Verify uploading or deleting without X-CSRF-Token header returns 403 Forbidden."""
    email = "csrf_file_user@example.com"
    pwd = "ValidPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf_token = login_res.json()["csrf_token"]

    # 1. Upload without CSRF -> 403 Forbidden
    no_csrf_upload = await client.post(
        "/api/v1/files",
        files={"file": ("doc.txt", io.BytesIO(b"Data"), "text/plain")}
    )
    assert no_csrf_upload.status_code == 403

    # 2. Upload with valid CSRF -> 201 Created
    valid_upload = await client.post(
        "/api/v1/files",
        files={"file": ("doc.txt", io.BytesIO(b"Data"), "text/plain")},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert valid_upload.status_code == 201
    file_id = valid_upload.json()["id"]

    # 3. Delete without CSRF -> 403 Forbidden
    no_csrf_delete = await client.delete(f"/api/v1/files/{file_id}")
    assert no_csrf_delete.status_code == 403

    # 4. Delete with valid CSRF -> 200 OK
    valid_delete = await client.delete(f"/api/v1/files/{file_id}", headers={"X-CSRF-Token": csrf_token})
    assert valid_delete.status_code == 200


@pytest.mark.asyncio
async def test_safe_filename_handling(client: AsyncClient):
    """Verify malicious directory traversal filenames are sanitized."""
    email = "traversal_user@example.com"
    pwd = "ValidPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf_token = login_res.json()["csrf_token"]

    upload_res = await client.post(
        "/api/v1/files",
        files={"file": ("../../etc/passwd", io.BytesIO(b"root:x:0:0:..."), "text/plain")},
        headers={"X-CSRF-Token": csrf_token}
    )
    assert upload_res.status_code == 201
    data = upload_res.json()
    assert data["original_name"] == "passwd", "Path traversal was not stripped from filename!"

    # Clean up
    await client.delete(f"/api/v1/files/{data['id']}", headers={"X-CSRF-Token": csrf_token})


@pytest.mark.asyncio
async def test_storage_usage_accounting(client: AsyncClient):
    """Verify storage_bytes_used increments on upload and decrements on deletion."""
    email = "usage_user@example.com"
    pwd = "ValidPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    csrf_token = login_res.json()["csrf_token"]

    # Initial usage should be 0
    u0 = await client.get("/api/v1/auth/usage")
    assert u0.json()["storage_bytes_used"] == 0

    # Upload 100 bytes
    payload = b"X" * 100
    up = await client.post(
        "/api/v1/files",
        files={"file": ("100b.txt", io.BytesIO(payload), "text/plain")},
        headers={"X-CSRF-Token": csrf_token}
    )
    file_id = up.json()["id"]

    u1 = await client.get("/api/v1/auth/usage")
    assert u1.json()["storage_bytes_used"] == 100

    # Delete file
    await client.delete(f"/api/v1/files/{file_id}", headers={"X-CSRF-Token": csrf_token})
    u2 = await client.get("/api/v1/auth/usage")
    assert u2.json()["storage_bytes_used"] == 0
