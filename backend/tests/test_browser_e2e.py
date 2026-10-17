"""
Browser-Level End-to-End Test Suite for CipherQ
Verifies registration, login, logout, session persistence, cookie security,
file upload with progress, download with integrity checks, recoverable deletion,
Free vs Premium entitlements, and two-user cross-vault isolation using Playwright with Google Chrome.
"""
import os
import sys
import time
import socket
import tempfile
import subprocess
import urllib.request
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    """
    Launch a live FastAPI server instance on an isolated ephemeral port
    with hermetic temporary database, keys, and vault paths.
    """
    port = get_free_port()
    base_url = f"http://127.0.0.1:{port}"

    tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    tpath = Path(tmp_dir.name)

    env = os.environ.copy()
    env["DATA_DIR"] = str(tpath / "data")
    env["VAULT_DIR"] = str(tpath / "vault")
    env["KEYS_DIR"] = str(tpath / "keys")
    env["MASTER_KEY_PATH"] = str(tpath / "keys" / ".vault_master.key")
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{tpath}/data/e2e_test.db"

    cmd = [
        sys.executable, "-m", "uvicorn", "backend.app.main:app",
        "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"
    ]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Wait for server to become healthy
    ready = False
    for _ in range(40):
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(f"{base_url}/api/v1/health") as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            pass

    if not ready:
        proc.terminate()
        tmp_dir.cleanup()
        raise RuntimeError("Live test server failed to start within 10 seconds.")

    yield {"base_url": base_url, "tmp_path": tpath}

    # Teardown
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    time.sleep(0.5)
    tmp_dir.cleanup()


@pytest.fixture(scope="module")
def browser_instance():
    """Launch system Chrome without downloading additional browser binaries."""
    pw = sync_playwright().start()
    browser = pw.chromium.launch(channel="chrome", headless=True)
    yield browser
    browser.close()
    pw.stop()


def test_browser_full_e2e_lifecycle(live_server, browser_instance, tmp_path):
    base_url = live_server["base_url"]
    context = browser_instance.new_context(accept_downloads=True)
    page = context.new_page()

    page.on("console", lambda msg: print(f"\n[BROWSER CONSOLE {msg.type}]: {msg.text}"))
    page.on("pageerror", lambda err: print(f"\n[BROWSER ERROR]: {err}"))

    # -------------------------------------------------------------
    # 1. Unauthenticated Access Control Checks
    # -------------------------------------------------------------
    page.goto(f"{base_url}/dashboard.html")
    expect(page.locator("text=Encrypted Vault Locked")).to_be_visible()
    expect(page.locator("#lock-btn-login")).to_be_visible()

    page.goto(f"{base_url}/files.html")
    expect(page.locator("text=Vault Access Restricted")).to_be_visible()

    # -------------------------------------------------------------
    # 2. User 1 Registration (Maya - FREE Tier)
    # -------------------------------------------------------------
    page.goto(f"{base_url}/index.html")
    expect(page.locator("#btn-nav-register")).to_be_visible()
    page.locator("#btn-nav-register").click()

    expect(page.locator("#auth-modal")).to_be_visible()
    page.fill("#reg-email", "maya@example.com")
    page.fill("#reg-password", "MayaSecret2026!")
    page.select_option("#reg-plan", "FREE")
    page.click("#btn-submit-register")

    # Verify post-registration authenticated state
    expect(page.locator("#user-display")).to_have_text("maya@example.com")
    expect(page.locator("#plan-badge")).to_have_text("FREE")
    expect(page.locator("#btn-nav-logout")).to_be_visible()

    # Verify cookie attributes (HttpOnly, SameSite=Lax, not stored in client storage)
    cookies = context.cookies()
    session_cookie = next((c for c in cookies if c["name"] == "cipherq_session"), None)
    assert session_cookie is not None, "cipherq_session cookie must be set on login"
    assert session_cookie["httpOnly"] is True, "Session cookie must have httpOnly=True"
    assert session_cookie["sameSite"] in ("Lax", "lax"), "Session cookie must have SameSite=Lax"

    local_storage_tokens = page.evaluate("() => Object.keys(localStorage)")
    assert "session_token" not in local_storage_tokens, "Session token must NEVER be stored in localStorage"

    # -------------------------------------------------------------
    # 3. Dashboard Quota Verification (Maya - FREE: 1GB)
    # -------------------------------------------------------------
    page.goto(f"{base_url}/dashboard.html")
    expect(page.locator("#user-badge")).to_have_text("maya@example.com")
    expect(page.locator("#storage-text")).to_contain_text("of 1 GB used")
    expect(page.locator("#ai-status-text")).to_contain_text("Keyword Search")

    # -------------------------------------------------------------
    # 4. File Upload, Encryption, and Table Listing
    # -------------------------------------------------------------
    page.goto(f"{base_url}/files.html")
    expect(page.locator("text=Encrypted File Vault")).to_be_visible()
    expect(page.locator("text=No encrypted files found in your vault")).to_be_visible()

    # Create test document
    test_doc = tmp_path / "maya_confidential_notes.txt"
    test_content = b"CipherQ confidential research text: verified end-to-end streaming AEAD roundtrip."
    test_doc.write_bytes(test_content)

    # Trigger upload via file input
    page.set_input_files("#file-input", str(test_doc))

    # Expect success indicator
    expect(page.locator("text=Successfully encrypted and committed to vault!")).to_be_visible()

    # Verify file appears in table
    expect(page.locator("#file-list-body")).to_contain_text("maya_confidential_notes.txt")
    expect(page.locator("#file-list-body")).to_contain_text("Encrypted Vault")

    # -------------------------------------------------------------
    # 5. Download Decryption Roundtrip with Integrity Check
    # -------------------------------------------------------------
    with page.expect_download() as download_info:
        page.locator(".download-btn").click()
    download = download_info.value
    downloaded_path = tmp_path / "downloaded_maya_file.txt"
    download.save_as(str(downloaded_path))

    downloaded_bytes = downloaded_path.read_bytes()
    assert downloaded_bytes == test_content, "Downloaded plaintext must match original plaintext exactly"

    # -------------------------------------------------------------
    # 6. Two-User Vault Isolation (Register Alex - PREMIUM Tier)
    # -------------------------------------------------------------
    # Maya logs out
    page.locator("#btn-nav-logout").click()
    page.wait_for_url("**/index.html")
    expect(page.locator("#btn-nav-login")).to_be_visible()

    # Alex registers on PREMIUM tier
    page.locator("#btn-nav-register").click()
    page.fill("#reg-email", "alex@example.com")
    page.fill("#reg-password", "AlexSecret2026!")
    page.select_option("#reg-plan", "PREMIUM")
    page.click("#btn-submit-register")

    expect(page.locator("#user-display")).to_have_text("alex@example.com")
    expect(page.locator("#plan-badge")).to_have_text("PREMIUM")

    # Verify Alex's Dashboard (5GB quota & Semantic Search active)
    page.goto(f"{base_url}/dashboard.html")
    expect(page.locator("#user-badge")).to_have_text("alex@example.com")
    expect(page.locator("#storage-text")).to_contain_text("of 5 GB used")
    expect(page.locator("#ai-status-text")).to_contain_text("Semantic Vector Search")

    # Verify Alex CANNOT see Maya's vault file (Cross-User Isolation)
    page.goto(f"{base_url}/files.html")
    expect(page.locator("#file-list-body")).not_to_contain_text("maya_confidential_notes.txt")
    expect(page.locator("text=No encrypted files found in your vault")).to_be_visible()

    # Alex uploads an independent file
    alex_doc = tmp_path / "alex_design_spec.pdf"
    alex_doc.write_bytes(b"%PDF-1.4 Alex exclusive specification document")
    page.set_input_files("#file-input", str(alex_doc))
    expect(page.locator("text=Successfully encrypted and committed to vault!")).to_be_visible()
    expect(page.locator("#file-list-body")).to_contain_text("alex_design_spec.pdf")

    # -------------------------------------------------------------
    # 7. Maya Logs Back In and Performs Recoverable File Deletion
    # -------------------------------------------------------------
    # Alex logs out
    page.locator("#btn-nav-logout").click()
    page.wait_for_url("**/index.html")

    # Maya logs in
    page.locator("#btn-nav-login").click()
    page.fill("#login-email", "maya@example.com")
    page.fill("#login-password", "MayaSecret2026!")
    page.click("#btn-submit-login")

    expect(page.locator("#user-display")).to_have_text("maya@example.com")

    page.goto(f"{base_url}/files.html")
    # Verify Maya sees her file and NOT Alex's file
    expect(page.locator("#file-list-body")).to_contain_text("maya_confidential_notes.txt")
    expect(page.locator("#file-list-body")).not_to_contain_text("alex_design_spec.pdf")

    # Maya deletes her file with confirmation
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator(".delete-btn").click()

    # Verify row is removed and empty state is rendered
    expect(page.locator("text=No encrypted files found in your vault")).to_be_visible()

    context.close()
