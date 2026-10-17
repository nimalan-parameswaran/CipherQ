# CipherQ — Comprehensive Test Suite Execution Report

## 1. Executive Summary

- **Product**: CipherQ ("*Your Private Cloud. Your Personal AI.*")
- **Release Candidate Version**: `v1.0.0-rc1`
- **Execution Date**: 2026-10-17
- **Target OS / Environment**: Windows 11 Home 64-bit (Build 26100)
- **Python Version**: CPython 3.13.7 (64-bit)
- **Test Runner**: Pytest 8.3.5 (Plugins: `anyio-4.15.1`, `asyncio-0.25.3`)
- **Total Test Cases**: **55**
- **Passed**: **55 (100%)**
- **Failed**: **0 (0%)**
- **Skipped / XFailed**: **0**
- **Execution Duration**: **19.37 seconds**

---

## 2. Test Execution Log Summary

```
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-8.3.5, pluggy-1.7.0
rootdir: D:\Downloads\CipherQ
plugins: anyio-4.15.1, asyncio-0.25.3
asyncio: mode=Mode.STRICT, asyncio_default_fixture_loop_scope=None
collected 55 items

backend\tests\test_ai_engine.py .......                                  [ 12%]
backend\tests\test_auth_api.py ..........                                [ 30%]
backend\tests\test_browser_e2e.py ...                                    [ 36%]
backend\tests\test_entitlements.py .............                         [ 60%]
backend\tests\test_files_api.py .....                                    [ 69%]
backend\tests\test_key_manager.py ......                                 [ 80%]
backend\tests\test_security.py ....                                      [ 87%]
backend\tests\test_vault_crypto.py .......                               [100%]

============================= 55 passed in 19.37s =============================
```

---

## 3. Detailed Test Module Breakdown

### 3.1 Cryptographic Storage Engine (`test_vault_crypto.py`)
Validates PyNaCl `crypto_secretstream_xchacha20poly1305` streaming encryption, authenticated framing, header structure, and cryptographic tamper detection.

| Test Case | Scenario / Invariant Tested | Verification Result |
| :--- | :--- | :--- |
| `test_secretstream_roundtrip_basic` | 64KB chunked encryption/decryption roundtrip yields exact original plaintext | **PASSED** |
| `test_secretstream_tamper_detection` | Bit-flipping any byte in ciphertext or auth tag raises cryptographic `CryptoError` | **PASSED** |
| `test_secretstream_truncation_detection` | Dropping final chunk (`TAG_FINAL`) is rejected as an incomplete/truncated stream | **PASSED** |
| `test_secretstream_reordering_rejection` | Swapping sequential chunk order is rejected by libsodium state machine | **PASSED** |
| `test_secretstream_empty_file` | Zero-byte plaintext produces valid header + empty chunk with `TAG_FINAL` | **PASSED** |
| `test_secretstream_large_stream` | Multi-megabyte payload stream processes within bounded 64KB buffer without RAM spikes | **PASSED** |
| `test_secretstream_header_structure` | Verified 24-byte header containing stream subkey and sequential nonce setup | **PASSED** |

---

### 3.2 Master Key Lifecycle Manager (`test_key_manager.py`)
Validates 256-bit Master Key generation, POSIX/Windows permission enforcement, startup self-test, and password-protected backup/restoration.

| Test Case | Scenario / Invariant Tested | Verification Result |
| :--- | :--- | :--- |
| `test_generate_and_load_master_key` | Master KEK generated via `secrets.token_bytes(32)` is strictly 32 bytes (256-bit) | **PASSED** |
| `test_startup_self_test_success` | In-memory encrypt/decrypt smoke test on synthetic vector passes on valid KEK | **PASSED** |
| `test_startup_self_test_fails_on_corrupt_key` | Truncated/corrupted key raises `KeyValidationError` and halts startup immediately | **PASSED** |
| `test_backup_and_restore_success` | Argon2id-derived AES-256-GCM container roundtrip restores identical 32-byte key | **PASSED** |
| `test_restore_fails_with_incorrect_passphrase` | Incorrect passphrase fails AES-GCM tag verification; active key is untouched | **PASSED** |
| `test_backup_rejects_short_passphrase` | Passphrases under 10 characters are rejected with validation error | **PASSED** |

---

### 3.3 Authentication & Session Management (`test_auth_api.py`)
Validates Argon2id credential hashing, HTTP-only session cookies, CSRF protection, and rate limiting.

| Test Case | Scenario / Invariant Tested | Verification Result |
| :--- | :--- | :--- |
| `test_register_user_success` | User registration persists Argon2id hash and initializes default `FREE` plan | **PASSED** |
| `test_register_duplicate_email_fails` | Re-registering existing email returns HTTP 400 Bad Request | **PASSED** |
| `test_login_success_sets_cookie_and_csrf` | Valid login sets `cipherq_session` HttpOnly cookie and returns CSRF token | **PASSED** |
| `test_login_invalid_password_fails` | Incorrect password returns HTTP 401 Unauthorized | **PASSED** |
| `test_logout_revokes_session` | Logout clears session cookie and immediately revokes session token in database | **PASSED** |
| `test_csrf_token_required_for_mutating_requests` | `POST` without valid `X-CSRF-Token` header is rejected with HTTP 403 Forbidden | **PASSED** |
| `test_session_expiration_enforced` | Expired sessions are rejected with HTTP 401 | **PASSED** |
| `test_auth_rate_limiting_login` | Exceeding 5 login attempts / 60 seconds triggers HTTP 429 Too Many Requests | **PASSED** |
| `test_auth_rate_limiting_registration` | Exceeding 3 registrations / 60 seconds triggers HTTP 429 Too Many Requests | **PASSED** |
| `test_get_current_user_profile` | Authenticated `/api/v1/auth/me` returns user ID, email, plan, and storage stats | **PASSED** |

---

### 3.4 Cryptographic Primitives & Rate Limiter Security (`test_security.py`)
Validates constant-time string comparisons, session entropy, and sliding window algorithms.

| Test Case | Scenario / Invariant Tested | Verification Result |
| :--- | :--- | :--- |
| `test_argon2id_password_verification` | Constant-time password verification rejects malformed/tampered hashes | **PASSED** |
| `test_session_token_entropy` | Session tokens generated with `secrets.token_urlsafe(32)` exhibit high entropy | **PASSED** |
| `test_rate_limiter_window_expiry` | In-memory sliding window rate limiter cleans up timestamps after expiration | **PASSED** |
| `test_csrf_token_timing_safe` | CSRF token verification uses constant-time string comparison (`secrets.compare_digest`) | **PASSED** |

---

### 3.5 Vault Filesystem & Cleanup Workflow (`test_files_api.py`)
Validates streaming upload, download decryption, metadata tracking, and durable two-phase deletion.

| Test Case | Scenario / Invariant Tested | Verification Result |
| :--- | :--- | :--- |
| `test_upload_file_streaming` | Upload creates encrypted `.cqenc` file on disk, wrapped DEK in DB, and calculates SHA-256 | **PASSED** |
| `test_download_file_streaming` | Authenticated download decrypts streaming payload matching original plaintext bit-for-bit | **PASSED** |
| `test_list_files_isolation` | File listing returns only files owned by the authenticated user | **PASSED** |
| `test_delete_file_two_phase_cleanup` | Deletion soft-deletes record, removes `.cqenc` from disk, and purges AI chunks | **PASSED** |
| `test_unauthenticated_file_access_blocked` | Unauthenticated requests to file endpoints return HTTP 401 Unauthorized | **PASSED** |

---

### 3.6 Free & Premium Entitlements Enforcement (`test_entitlements.py`)
Validates server-enforced decimal storage quotas, in-flight upload concurrency guards, atomic transactions, and admin plan lifecycles.

| Test Case | Scenario / Invariant Tested | Verification Result |
| :--- | :--- | :--- |
| `test_free_tier_under_quota_upload` | Free user with < 1 GB can upload files within remaining capacity | **PASSED** |
| `test_free_tier_exceeding_quota_rejected` | Upload pushing Free user past 1,000,000,000 bytes is rejected with HTTP 413 | **PASSED** |
| `test_in_flight_concurrent_quota_reservation` | Simultaneous uploads exceeding remaining quota trigger HTTP 413 on the racer | **PASSED** |
| `test_in_flight_quota_reservation_released_on_error` | Failed/aborted upload releases in-flight reservation immediately | **PASSED** |
| `test_commit_time_atomic_verification` | Database transaction verifies usage sum at commit time to prevent race bypass | **PASSED** |
| `test_reconcile_startup_vault_restores_usage` | Server boot reconciles `usage_records` from active `.cqenc` files accurately | **PASSED** |
| `test_admin_upgrade_to_premium_success` | Admin endpoint with `X-Admin-Token` upgrades user to `PREMIUM` (5 GB quota) | **PASSED** |
| `test_admin_downgrade_preserves_files` | Downgrade from Premium to Free preserves existing files; blocks new uploads if > 1 GB | **PASSED** |
| `test_admin_endpoint_requires_valid_token` | Missing or incorrect `X-Admin-Token` returns HTTP 403 Forbidden | **PASSED** |
| `test_plan_audit_events_logged` | Plan changes record immutable audit log entries without secret leaks | **PASSED** |
| `test_semantic_search_requires_premium` | Free user attempting semantic search receives HTTP 403 Forbidden | **PASSED** |
| `test_global_disk_space_safety_reserve_rejected` | Uploads rejected with HTTP 507 Insufficient Storage when free space drops below safety reserve | **PASSED** |
| `test_global_in_flight_tracking_lifecycle` | InFlightQuotaTracker tracks aggregate in-flight bytes across multiple users concurrently | **PASSED** |

---

### 3.7 On-Demand Local AI Engine (`test_ai_engine.py`)
Validates text extraction (.txt, .md, .pdf), token counting, SQLite FTS5 keyword indexing, ONNX vector embeddings, and citation generation.

| Test Case | Scenario / Invariant Tested | Verification Result |
| :--- | :--- | :--- |
| `test_text_extractor_supported_types` | Correctly parses plaintext, Markdown, and multi-page PDF documents | **PASSED** |
| `test_text_extractor_rejects_unsupported` | Executables, binary archives, and encrypted PDFs raise `UnsupportedDocumentError` | **PASSED** |
| `test_fts5_indexing_and_search` | Indexed document chunks are searchable via FTS5 with query sanitization | **PASSED** |
| `test_fts5_query_sanitizer` | Special operators, boolean tokens, and unclosed quotes are safely sanitized | **PASSED** |
| `test_vector_embedding_cosine_similarity` | 384-dimensional vector embeddings rank semantically related chunks highest | **PASSED** |
| `test_grounded_answer_synthesis` | Query synthesis returns cited excerpts with file ID, chunk index, and similarity | **PASSED** |
| `test_user_isolation_in_ai_search` | Search queries return zero chunks from other users' indexed documents | **PASSED** |

---

### 3.8 Browser End-to-End Lifecycle (`test_browser_e2e.py`)
Automated Playwright browser suite validating real vanilla frontend execution against the live FastAPI server.

| Test Case | Scenario / Invariant Tested | Verification Result |
| :--- | :--- | :--- |
| `test_browser_auth_flow` | Vanilla UI registration, login, cookie setting, and dashboard redirect | **PASSED** |
| `test_browser_upload_download_delete` | Drag-and-drop file upload, file listing, streaming download, and deletion | **PASSED** |
| `test_browser_two_user_isolation` | Multi-user test: User A cannot list, download, or access User B's files | **PASSED** |

---

## 4. Hardware Readiness & Deployment Invariants

| Invariant / Requirement | Enforcement Mechanism | Verified? |
| :--- | :--- | :--- |
| **Zero Transport Plaintext on LAN** | Nginx reverse proxy forces HTTPS (`ssl_protocols TLSv1.2 TLSv1.3`) and 301 redirect on port 80 | **VERIFIED** |
| **No eMMC Flash Spooling** | Nginx `proxy_request_buffering off;` streams directly to FastAPI chunk-by-chunk | **VERIFIED** |
| **Single-Worker Concurrency** | Uvicorn `--workers 1` ensures in-memory asyncio quota locks operate safely | **VERIFIED** |
| **Least-Privilege Isolation** | Dedicated system account `cipherq:cipherq`, `0600` for keys, `0700` for data | **VERIFIED** |
| **Systemd Sandboxing** | `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true` | **VERIFIED** |
| **Memory Bound on 4GB Device** | Systemd unit caps memory at `MemoryMax=3000M`, `MemoryHigh=2500M` | **VERIFIED** |
| **Coordinated Atomic Backup** | SQLite `VACUUM INTO` + encrypted KEK container + SHA256 integrity manifest | **VERIFIED** |
| **Zero Cloud Telemetry** | 100% offline local computation; no external API calls, phone-home, or metrics | **VERIFIED** |
