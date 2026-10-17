# CipherQ — Technical Architecture Specification

**Version**: 1.0.0-draft  
**Status**: Approved Specification  
**Target Hardware**: Arduino UNO Q (4GB RAM, 32GB eMMC, Debian Linux)  
**Development Baseline**: Local Laptop (FastAPI, Python 3.13, Vanilla HTML5/CSS3/JS)

---

## 1. System Topology & Serving Architecture

To eliminate CORS complexity, mixed-content blocking, and cookie partitioning during development and prototype demonstration, CipherQ implements a **Same-Origin Architecture**:

```
+-------------------------------------------------------------------------+
|                  Same-Origin Host (http://localhost:8000)                |
|                                                                         |
|  +--------------------------------+  +--------------------------------+ |
|  |       Static Web Frontend      |  |      FastAPI Backend Engine    | |
|  |  (Vanilla HTML5 / CSS3 / ESM)  |  |      (Python 3.13 / Uvicorn)   | |
|  |                                |  |                                | |
|  |  /                             |  |  /api/v1/auth/*                | |
|  |  /dashboard.html               |  |  /api/v1/files/*               | |
|  |  /files.html                   |  |  /api/v1/ai/*                  | |
|  |  /css/styles.css               |  |  /api/v1/usage/*               | |
|  |  /js/app.js                    |  |  /api/v1/health                | |
|  +--------------------------------+  +--------------------------------+ |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|                         Storage & Security Layer                        |
|                                                                         |
|  +---------------------+  +---------------------+  +-----------------+  |
|  | SQLite Database     |  | Encrypted Vault     |  | Master KEK      |  |
|  | (data/cipherq.db)   |  | (data/vault/*.cqenc)|  | (.vault_master) |  |
|  +---------------------+  +---------------------+  +-----------------+  |
+-------------------------------------------------------------------------+
```

### Network Security & LAN HTTPS Boundary
- **Localhost Development**: Running on `http://127.0.0.1:8000` or `http://localhost:8000` is permitted for local development because the browser treats `localhost` as a secure context.
- **LAN Access Warning**: Plain HTTP over a local network (`http://192.168.x.x:8000`) transmits session cookies and file chunks unencrypted over Wi-Fi/Ethernet.
- **Production LAN Deployment**: When running on the Arduino UNO Q accessible to home/office devices, one of the following TLS mechanisms is required:
  1. *Local Private PKI (`mkcert`)*: Installs a local trusted CA certificate on client browsers.
  2. *Split-Horizon DNS + Let's Encrypt*: Domain pointing to internal LAN IP with automated certificate renewal.
  3. *Encrypted Overlay Network*: Tailscale / WireGuard private network with automatic HTTPS.

---

## 2. Authentication & Session Security

- **Password Storage**: Passwords hashed with **Argon2id** (`argon2-cffi`), memory cost 64MB (`m_cost=65536`), time cost 3 (`t_cost=3`), parallelism 4 (`p_cost=4`).
- **Session Tokens**: 256-bit cryptographically secure random tokens generated via `secrets.token_urlsafe(32)`.
- **Session Transport**: Stored in a database-backed session table (hashed with SHA-256); issued to the browser via:
  - `HttpOnly`: Inaccessible to JavaScript (mitigates XSS).
  - `SameSite=Lax`: Defends against Cross-Site Request Forgery (CSRF).
  - `Secure`: Required in production when TLS is active.
- **CSRF Token**: Double-submit cookie or custom header `X-CSRF-Token` validated against active session on all mutating HTTP methods (`POST`, `PUT`, `PATCH`, `DELETE`).

---

## 3. Master Key Lifecycle (Option B - Server-Managed Vault)

CipherQ uses a two-tier key hierarchy:
1. **Master Key Encryption Key (KEK)**: 256-bit AES key.
2. **Data Encryption Key (DEK)**: 256-bit random key generated uniquely per file.

### Key Management Rules:
1. **Storage Outside Repository**: Stored in `.vault_master.key` in the project root, strictly excluded in `.gitignore`.
2. **File Permissions**: Must have owner-only permissions (`0600` on POSIX systems; restricted DACL on Windows). Backend startup aborts immediately if permissions are overly permissive.
3. **Startup Validation Self-Test**: During FastAPI startup lifespan, the server:
   - Verifies the file exists and is strictly 32 bytes (256 bits).
   - Validates file permissions.
   - Executes an in-memory encrypt/decrypt cycle on synthetic test data.
   - If any check fails, server logs an emergency alert and exits.
4. **Encrypted Backup & Recovery**:
   - `python -m app.core.key_manager backup`: Prompts for an administrator passphrase, derives a key via Argon2id, and exports an authenticated AES-256-GCM backup container (`cipherq_kek_backup.enc`).
   - `python -m app.core.key_manager restore <path>`: Prompts for the passphrase, verifies the authentication tag, and restores `.vault_master.key`.
   - *Limitation Disclosure*: If `.vault_master.key` is lost without a backup, all encrypted files in the vault are permanently unrecoverable.

---

## 4. Cryptographic Storage Engine: Vetted Streaming AEAD

CipherQ strictly prohibits custom cryptographic framing. The storage engine evaluates two vetted streaming AEAD constructions:

```mermaid
flowchart LR
    subgraph Client ["Client Browser"]
        StreamUpload["Stream Upload (64KB chunks)"]
    end
    
    subgraph StorageEngine ["FastAPI Streaming Engine"]
        DEK["Generate File DEK (256-bit)"]
        Wrap["Wrap DEK with Master KEK"]
        StreamAEAD["Vetted Streaming AEAD Engine\n(Tink or PyNaCl secretstream)"]
        Hash["Compute Plaintext SHA-256"]
    end

    subgraph Disk ["Disk Vault"]
        TmpFile["Atomic Staging (.tmp)"]
        FinalFile["Final Storage (.cqenc)"]
    end

    StreamUpload --> StreamAEAD
    DEK --> Wrap
    StreamAEAD --> Hash
    StreamAEAD --> TmpFile
    TmpFile -->|Atomic Rename on Success| FinalFile
```

### Comparison Matrix: Google Tink vs. PyNaCl / libsodium

| Evaluation Dimension | Google Tink `StreamingAead` | PyNaCl / libsodium `secretstream` |
| :--- | :--- | :--- |
| **Tested Version** | `tink 1.16.1` (Python 3.13) | `pynacl 1.6.2` (Python 3.13) |
| **Cryptographic Scheme** | AES-256-GCM-HKDF (`AES256_GCM_HKDF_4KB`) | XChaCha20-Poly1305 state machine |
| **Licence** | Apache 2.0 | ISC License (libsodium) / Apache 2.0 (PyNaCl) |
| **Framing Specification** | Audited Tink segment framing | Audited libsodium `crypto_secretstream` format |
| **Reorder & Truncation Resistance** | Native: segment tags & chunk counters | Native: `TAG_FINAL` / sequential state |
| **Python API** | Native `io.RawIOBase` file stream objects | CFFI state machine (`push` / `pull` blocks) |
| **Platform Compatibility** | x86_64 and aarch64 binary wheels; potential armv7l build requirement | Standard C libsodium; supported across virtually all Linux architectures |

---

## 5. Deletion & Cleanup Architecture: Durable & Conservative

To avoid distributed state corruption across SQLite and the filesystem, CipherQ implements a **Durable, Retryable Cleanup Workflow**:

### Two-Phase Deletion Flow
1. **User Request**: User sends `DELETE /api/v1/files/{file_id}`.
2. **Phase 1 (Database Soft-Delete)**:
   - File status updated to `PENDING_DELETION`.
   - File immediately disappears from user listings and API queries.
   - Deletion task inserted into SQLite `cleanup_queue` table (`status='PENDING'`).
3. **Phase 2 (Asynchronous / Immediate Purge)**:
   - Worker unlinks `{file_id}.cqenc` from disk via `os.remove`.
   - Worker purges all AI chunks, embeddings, and FTS5 rows linked to `file_id`.
   - Worker marks task as `COMPLETED` and purges the file record from `files`.

### Conservative Startup Reconciliation
On server startup, a background reconciliation routine runs:
1. **Active Upload Safety**: Temporary upload staging files (`*.tmp`) modified within the last **30 minutes** are strictly preserved. This prevents server restarts from aborting active client uploads.
2. **Stale Temp Cleanup**: Only `.tmp` files older than 1 hour with no active session are unlinked.
3. **Orphan Storage Quarantine**: Files on disk with no matching record in the database are moved to `vault/orphans/` with a logged warning, preventing accidental data loss.
4. **Retryable Deletions**: Any job in `cleanup_queue` with `status IN ('PENDING', 'FAILED')` is resumed and retried.

---

## 6. AI Data Lifecycle: Ephemeral vs. Persistent

```
+--------------------------------------------------------------------------+
|                        Ephemeral In-Memory Processing                    |
|                                                                          |
|  [Decrypted Stream] ---> [Raw PDF/Text] ---> [Tokens] ---> [Activations] |
|                                                                          |
|  * Strictly in volatile RAM during active indexing request               |
|  * Buffers explicitly closed and dereferenced ('del buf', 'gc.collect()')|
|  * ZERO intermediate plaintext files written to persistent disk          |
+--------------------------------------------------------------------------+
                                     |
                         Extract & Embeddings Chunks
                                     v
+--------------------------------------------------------------------------+
|                         Persistent AI-Derived Data                       |
|                                                                          |
|  SQLite Database:                                                        |
|  - ai_chunks table (chunk text, token count, file_id FK)                 |
|  - fts5_document_chunks (keyword search index)                           |
|  - vector_embeddings (float arrays for semantic similarity)              |
|                                                                          |
|  * Purged durably via cleanup_queue upon file deletion                   |
+--------------------------------------------------------------------------+
```

---

## 7. Database Schema (SQLite)

```sql
-- Users Table
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    plan_type TEXT NOT NULL DEFAULT 'FREE', -- 'FREE' or 'PREMIUM'
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sessions Table
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- File Vault Metadata
CREATE TABLE files (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    storage_name TEXT NOT NULL UNIQUE,
    file_size_bytes INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    sha256_hash TEXT NOT NULL,
    wrapped_dek BLOB NOT NULL,
    nonce_or_header BLOB NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE', -- 'ACTIVE', 'PENDING_DELETION'
    is_indexed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Durable Cleanup Queue
CREATE TABLE cleanup_queue (
    task_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'IN_PROGRESS', 'FAILED', 'COMPLETED'
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- AI Chunks Table
CREATE TABLE ai_chunks (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Storage & AI Usage Records
CREATE TABLE usage_records (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    storage_bytes_used INTEGER NOT NULL DEFAULT 0,
    ai_queries_today INTEGER NOT NULL DEFAULT 0,
    last_query_date TEXT
);

-- Plan Audit Events
CREATE TABLE plan_audit_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    old_plan TEXT NOT NULL,
    new_plan TEXT NOT NULL,
    changed_by TEXT NOT NULL, -- 'admin_api', 'cli_admin'
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. Entitlements, Quotas & Administrative Plan Management

### 7.1 Authoritative Quota Standards
- Quotas are strictly accounted in **decimal bytes**:
  - `FREE`: **1 GB** (`1,000,000,000` bytes)
  - `PREMIUM`: **5 GB** (`5,000,000,000` bytes)
- **Accounted Storage Metric**: The authoritative billable storage metric is the exact physical ciphertext size stored in `data/vault/{file_id}.cqenc` on disk.
- **Temporary Upload Staging**: In-flight upload chunks writing to `.tmp` files are tracked concurrently by `InFlightQuotaTracker`. If concurrent uploads race for remaining capacity, only uploads fitting within the remaining quota succeed; competing uploads exceeding the limit receive HTTP 413.
- **Startup Reconciliation**: `reconcile_startup_vault` recalculates `UsageRecord.storage_bytes_used` across all users on every boot via `SELECT COALESCE(SUM(file_size_bytes), 0) FROM files WHERE user_id = :u_id AND status = 'ACTIVE'`, eliminating negative, stale, or double-counted usage.

### 7.2 Plan Upgrade and Downgrade Lifecycle
- **Administrative Control**: Subscription tiers are modified via authenticated backend endpoints (`POST /api/v1/admin/users/plan` with `X-Admin-Token`) or host CLI (`python -m backend.app.cli.manage_plan <email> <FREE|PREMIUM>`). Ordinary user sessions have zero access to plan escalation.
- **Immediate Upgrade**: Applying a plan upgrade updates database state immediately; active sessions enjoy 5 GB quota and semantic capabilities on the subsequent request.
- **Downgrade Preservation**: Downgrading an account that holds more than 1 GB preserves all existing encrypted files, downloads, and FTS5 keyword searches. New uploads are blocked with HTTP 413 until the user deletes enough files to drop below 1 GB.
- **Audit Logging**: Every plan modification is durably logged to `plan_audit_events` with timestamp, actor, previous plan, target plan, and reason with zero secrets logged.

---

## 8. Deployment Architecture: Hardened Debian Linux & Arduino UNO Q

### 8.1 Network Perimeter and Reverse Proxy Topology
In production deployment on Debian 12 (Bookworm) targeting the Arduino UNO Q, CipherQ enforces strict defense-in-depth:

```
[ LAN Clients ] ---> HTTPS (Port 443) ---> [ Nginx Reverse Proxy ]
                                                    | (127.0.0.1:8000)
                                                    v
                                    [ Systemd Hardened Sandbox ]
                                    - User: cipherq (unprivileged)
                                    - MemoryMax: 3000M
                                    - ProtectSystem: strict
                                    - ProtectHome: true
                                    - Uvicorn (workers=1)
                                            |
                                    [ Storage Layer (0700/0600) ]
                                    - /opt/cipherq/data/cipherq.db
                                    - /opt/cipherq/data/vault/*.cqenc
                                    - /opt/cipherq/keys/.vault_master.key
```

1. **Loopback-Only ASGI Server**: Uvicorn is bound strictly to `127.0.0.1:8000`. Plain HTTP is never exposed to the local network interface.
2. **Streaming AEAD Reverse Proxy Optimization**:
   - `proxy_request_buffering off;`: Ensures multi-gigabyte client uploads stream directly chunk-by-chunk into the PyNaCl encryption engine, preventing Nginx from spooling temporary upload bodies to `/var/lib/nginx` on the 32GB eMMC flash.
   - `proxy_buffering off;`: Decrypted download chunks stream directly to the client without intermediate disk or memory buffering.
3. **Single-Worker Concurrency Architecture (`workers=1`)**:
   - Uvicorn runs with a single asynchronous worker process.
   - Guarantees `InFlightQuotaTracker`'s in-memory asyncio locks operate authoritatively without requiring a distributed locking coordinator (such as Redis), maintaining a lightweight memory footprint under 4GB RAM.

### 8.2 Systemd Security Sandboxing
The `cipherq.service` unit enforces Linux kernel sandboxing:
- **Least-Privilege Identity**: Runs under dedicated unprivileged system account `cipherq:cipherq` (`/usr/sbin/nologin`).
- **Filesystem Lockdown**: `ProtectSystem=strict` (mounts `/usr`, `/boot`, `/etc` read-only) and `ProtectHome=true` (denies access to `/home` and `/root`).
- **Explicit Writable Paths**: Restricted exclusively to `ReadWritePaths=/opt/cipherq/data /opt/cipherq/keys /tmp /var/log/cipherq`.
- **Capability Dropping**: `NoNewPrivileges=true`, `CapabilityBoundingSet=`, and `AmbientCapabilities=` drop all Linux kernel capabilities.
- **Resource Limits**: `MemoryHigh=2500M` (initiates proactive page reclaim) and `MemoryMax=3000M` (hard cap protecting the OS and systemd from OOM).

### 8.3 Coordinated Backup and Disaster Recovery Architecture
To prevent state skew between the relational database and the filesystem vault:
1. **Atomic SQLite Snapshot**: Uses `sqlite3 "VACUUM INTO '...'"` to generate an atomic, non-blocking, transactionally consistent database snapshot without table locks or corruption risk.
2. **Argon2id-Wrapped Master KEK**: Master KEK is exported to an encrypted container (`cipherq_kek_backup.enc`) protected by an admin passphrase via `backend.app.core.key_manager backup`.
3. **Vault Snapshot and Manifest**: Active `.cqenc` vault files are archived and sealed with a SHA-256 integrity manifest (`manifest.sha256`) before bundling into a `0600` tar archive.
4. **Disaster Recovery**: `restore.sh` validates cryptographic checksums, halts service activity, restores the database, restores KEK after passphrase verification, and re-validates startup reconciliation.

### 8.4 Global Storage Safety Margin & Host Headroom Protection
To protect embedded single-board computers from root partition exhaustion:
1. **Host Headroom Reserve (`MIN_FREE_DISK_BYTES`)**: In addition to per-user quotas (1 GB Free / 5 GB Premium), CipherQ enforces a global safety reserve (default: 1 GB) on the vault partition.
2. **Pre-Allocation & Chunk-Time Verification**: `InFlightQuotaTracker` checks available host filesystem space via `shutil.disk_usage` before accepting an upload and while streaming 64 KB chunks.
3. **Graceful Rejection**: If host free space drops below the safety margin, new writes are halted with `HTTP 507 Insufficient Storage`, protecting the operating system, journal logs, and SQLite write-ahead log (WAL) from disk full crashes.



