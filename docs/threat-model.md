# CipherQ — Threat Model & Security Boundary Analysis

**Version**: 1.0.0-draft  
**Methodology**: STRIDE Model (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege)  
**Target Hardware**: Arduino UNO Q (4GB RAM, 32GB eMMC, Debian Linux)  
**Development Baseline**: Local Laptop (FastAPI, Python 3.13)

---

## 1. Security Architecture & Trust Boundaries

```
[Untrusted Network / Public Internet]
                 |
======== [BOUNDARY 1: Network Boundary] =====================================
                 | (Requires TLS / HTTPS; Plain HTTP untrusted on LAN)
                 v
[Client Web Browser (Same-Origin Vanilla JS)]
                 |
======== [BOUNDARY 2: Web Session Boundary] =================================
                 | (HttpOnly, SameSite=Lax Session Cookies, CSRF Token)
                 v
[FastAPI Application Process (Memory Space)]
  - Auth Service (Argon2id)
  - Streaming Crypto Engine (Vetted Streaming AEAD)
  - On-Demand AI Pipeline (In-Memory Processing)
                 |
======== [BOUNDARY 3: Process / OS Boundary] ================================
                 | (File Permissions 0600 on Master Key)
                 v
[Host Filesystem & Hardware Storage]
  - SQLite Database (`data/cipherq.db`)
  - Encrypted Storage Vault (`data/vault/*.cqenc`)
  - Master Key Encryption Key (`.vault_master.key`)
  - 32GB eMMC Flash Memory (Hardware Wear-Leveling)
```

---

## 2. Honest Disclosures & Physical Limitations

### 2.1 Not End-to-End Encrypted (E2EE) / Zero-Knowledge
- **Reality**: Because document text must be read to generate search embeddings, answer questions locally, and provide streaming downloads, the server backend holds the Master Key (KEK) and decrypts files in volatile RAM.
- **Threat Implication**: Anyone with root administrative access to the Debian operating system or physical RAM bus can extract the Master KEK and inspect decrypted buffers.
- **Product Claim**: CipherQ provides **authenticated encryption at rest**, not client-side zero-knowledge encryption.

### 2.2 Volatile Memory & Plaintext Erasure Boundaries
- **Reality**: In managed runtimes like Python, memory allocations, string immutability, garbage collection cycles, and OS swap paging mean volatile RAM cannot be forensically wiped with 100% cryptographic certainty without low-level OS primitives (`mlock`, C-level zeroing).
- **Mitigation**: Buffers are explicitly dereferenced and garbage collection is called immediately after document chunking. No intermediate plaintext is written to disk.
- **Boundary**: Absolute protection against cold-boot or memory-dump attacks requires hardware-level RAM encryption or disabling OS swap.

### 2.3 Flash Memory (eMMC) Wear-Leveling vs. Forensic Erasure
- **Reality**: Deleting a file (`os.remove`) is a **logical filesystem deletion** (unlinking inode from ext4). On 32GB eMMC flash memory, the Flash Translation Layer (FTL) uses wear-leveling algorithms that distribute writes across physical blocks. Unlinked ciphertext or temporary data may physically persist on NAND flash cells until overwritten or sanitized via hardware `blkdiscard`/TRIM.
- **Boundary**: Protection against forensic physical chip removal requires full-disk encryption (eMMC LUKS) at the OS level.

---

## 3. STRIDE Threat Analysis & Mitigations

| Threat Category | Specific Attack Vector | Potential Impact | Implemented Mitigation & Verification |
| :--- | :--- | :--- | :--- |
| **Spoofing** | Attacker guesses password or brute-forces login | Account takeover | Argon2id password hashing (`m=64MB, t=3, p=4`) + exponential login rate limiting. |
| **Spoofing** | Attacker steals or forges session token | Session hijacking | Cryptographically secure 256-bit random session tokens; stored hashed in DB; transmitted via `HttpOnly`, `SameSite=Lax` cookies. |
| **Tampering** | Attacker flips bits in encrypted `.cqenc` file on disk | Silent corruption or plaintext manipulation | Vetted Streaming AEAD (Tink or PyNaCl secretstream). Every chunk contains an authenticated tag; tampering causes immediate decryption abort. |
| **Tampering** | Truncation attack: Attacker chops off the end of a ciphertext stream | Client receives incomplete file without warning | Enforced streaming framing: Missing `TAG_FINAL` or end-of-stream segment flag raises an integrity failure. |
| **Tampering** | Chunk reordering: Attacker swaps two 64KB ciphertext chunks | Scrambled document content | Stream construction binds chunk counters/sequence numbers into Associated Data (AD). Reordered chunks trigger an immediate authentication error. |
| **Tampering** | Cross-Site Request Forgery (CSRF) | Browser executes unauthorized deletion/upload | Custom header `X-CSRF-Token` validated on all state-changing HTTP methods (`POST`, `PATCH`, `DELETE`). |
| **Repudiation** | User denies uploading or deleting a file | Lack of accountability | Structured audit logging of all file uploads, downloads, and deletion tasks with timestamp and user ID (no plaintext logged). |
| **Information Disclosure** | Plaintext leakage over Wi-Fi / Local Area Network | Eavesdropper captures files or session cookies | Same-origin architecture; plain HTTP strictly restricted to `localhost`; LAN deployment explicitly requires TLS (mkcert / private PKI). |
| **Information Disclosure** | Master KEK checked into Git or readable by other users | Entire vault compromised | Master KEK stored in `.vault_master.key` outside Git; enforced `0600` permissions; startup fails if permissions are permissive. |
| **Information Disclosure** | Unencrypted scratch files left on disk during AI extraction | Data remnant leakage | In-memory text extraction using `io.BytesIO`; zero intermediate unencrypted files created on disk. |
| **Information Disclosure** | Cross-User File Access (IDOR) | User A downloads User B's file by guessing file ID | Every file lookup strictly joins on `user_id == current_user.id` in database query. Unowned file returns `404 Not Found`. |
| **Denial of Service** | Gigabyte file upload exhausts 4GB RAM on Arduino UNO Q | Server OOM crash | Streaming chunk-by-chunk processing (64KB chunks); RAM overhead remains constant (`< 1MB`) regardless of file size. |
| **Denial of Service** | Free user floods AI Q&A endpoint | CPU starvation on 4-core processor | Entitlement check returns `403 Forbidden` to Free users; Premium users constrained to max 1 concurrent AI query with queue limit. |
| **Denial of Service** | Low memory crash during local LLM generation | System kernel panic | Dynamic RAM monitor checks available system memory before running local inference; falls back to keyword search if free RAM < 500MB. |
| **Elevation of Privilege** | Free user modifies client JS to unlock Premium AI features | Bypasses billing and hardware restrictions | All quotas, storage caps, and AI capabilities are validated server-side on every request. Frontend UI reflects, but never enforces, entitlement state. |
| **Elevation of Privilege** | Attacker calls administrative plan change route | Unauthorized tier upgrade to Premium | `POST /api/v1/admin/users/plan` strictly validates server `X-Admin-Token`; ordinary session cookies receive `403 Forbidden`. Plan changes recorded in immutable `plan_audit_events`. |
| **Denial of Service** | Concurrent upload race condition: Attacker fires parallel uploads to exceed storage quota | Unbounded physical disk exhaustion beyond quota cap | `InFlightQuotaTracker` reserves streaming quota across concurrent requests; commit-time atomic transaction re-checks usage; rejects overages with HTTP 413. |
| **Denial of Service** | Usage drift after interrupted uploads, crashes, or aborted deletions | Artificial quota starvation or under-accounting | `reconcile_startup_vault` authoritative recalculation sums active files on startup; `.tmp` files older than 1h unlinked; failed tasks retried via `cleanup_queue`. |

---

## 4. Consolidated Known-Limitations and Security-Risk Register

This register consolidates all known architectural limitations, assumptions, and residual security risks for CipherQ v1.0.0-rc1:

| Risk ID | Risk Description | Severity | Attack Preconditions | Implemented Mitigation | Residual Risk & Operational Guidance |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **RISK-01** | **Physical Device Theft / Flash Chip Removal** | **HIGH** | Attacker has physical possession of Arduino UNO Q hardware. | Encrypted `.cqenc` vault files and wrapped DEKs prevent immediate file access. | **RESIDUAL RISK**: Master KEK resides in `/opt/cipherq/keys/.vault_master.key`. Without full-disk encryption (LUKS), physical chip dump allows key extraction. Recommend OS-level LUKS on eMMC. |
| **RISK-02** | **Irrecoverable KEK Loss** | **CRITICAL** | Storage failure, corrupt flash, or unbacked-up device reflash. | Coordinated `backup.sh` exports password-protected Argon2id-wrapped KEK container. | **RESIDUAL RISK**: If `.vault_master.key` is lost and no encrypted backup exists, all vault ciphertext is mathematically impossible to recover. |
| **RISK-03** | **Volatile Memory Plaintext Remanence** | **MEDIUM** | Root compromise, memory bus inspection, or unencrypted swap analysis. | Decrypted plaintext exists strictly in volatile RAM; buffers explicitly closed (`del buf`, `gc.collect()`). Zero disk scratch files. | **RESIDUAL RISK**: CPython managed heap does not guarantee zeroed memory pages. Disable OS swap or use encrypted swap (`cryptswap`). |
| **RISK-04** | **NAND Flash Wear-Leveling Remanence** | **MEDIUM** | Physical flash memory analysis following file deletion. | Two-phase cleanup unlinks `.cqenc` and purges AI chunks from SQLite database. | **RESIDUAL RISK**: eMMC Flash Translation Layer (FTL) remaps physical blocks. Logical deletion does not zero physical NAND cells. |
| **RISK-05** | **LAN Cleartext Eavesdropping** | **HIGH** | Client connects to CipherQ over unencrypted Wi-Fi/LAN via plain HTTP. | Production architecture mandates Nginx reverse proxy with TLS (port 443) and 301 HTTP redirect on port 80. | **RESIDUAL RISK**: If user bypasses Nginx and binds FastAPI directly to `0.0.0.0:8000`, session cookies and credentials are exposed on LAN. Uvicorn bound strictly to `127.0.0.1`. |
| **RISK-06** | **Multi-Worker In-Memory Quota Race** | **MEDIUM** | Administrator configures Uvicorn with `--workers > 1`. | Uvicorn pinned to `--workers 1` in systemd unit. In-memory `InFlightQuotaTracker` operates authoritatively. | **RESIDUAL RISK**: Running multiple worker processes bypasses in-memory locks. Multi-process clustering requires distributed locking (e.g. Redis). |
| **RISK-07** | **Host Storage Headroom Exhaustion** | **HIGH** | Multiple users upload files concurrently, filling the 32GB eMMC flash. | `MIN_FREE_DISK_BYTES` (1 GB reserve) actively checked before and during uploads; rejects overages with HTTP 507. | **RESIDUAL RISK**: External OS writes (large apt upgrades, unrotated systemd journal) can consume disk outside CipherQ's awareness. |
| **RISK-08** | **Default Admin Token in Production** | **HIGH** | Administrator deploys application with unchanged default dev token. | Startup check fast-fails in production mode if default token is detected. Default token removed from UI prompts. | **RESIDUAL RISK**: Weak or leaked administrator tokens allow unauthorized subscription modifications. Enforce `openssl rand -hex 32`. |


