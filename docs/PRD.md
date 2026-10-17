# CipherQ — Product Requirements Document (PRD)

**Version**: 1.0.0-draft  
**Target Hardware**: Arduino UNO Q (4GB RAM, 32GB eMMC, Debian Linux)  
**Development Baseline**: Local Laptop (Python 3.13, Windows, Vanilla HTML5/CSS3/JS, FastAPI)  
**Tagline**: *Your Private Cloud. Your Personal AI.*

---

## 1. Executive Summary & Vision

CipherQ is a secure, resource-conscious personal cloud vault designed to run on single-board hardware (specifically the **Arduino UNO Q** with 4GB RAM). It enables users to store, decrypt, download, and optionally search their private documents using local AI without transmitting sensitive contents to third-party cloud providers or external AI APIs.

### Core Value Propositions
1. **Authenticated Encryption at Rest**: Every stored file is protected with a per-file Data Encryption Key (DEK) wrapped under a server-managed Master Key (KEK) using audited streaming authenticated encryption.
2. **Local AI Without External Leakage**: On-demand document search and retrieval run strictly inside the local execution environment; document text never exits the device.
3. **Resource Bound for 4GB Hardware**: Architecture strictly limits peak memory consumption and concurrency to ensure stability on Debian Linux within 4GB RAM.
4. **Transparent Security Model**: Honest, accurate product disclosures: CipherQ is a **server-managed encrypted vault**, not an end-to-end encrypted (E2EE) zero-knowledge system, because local AI and downloads require server-side in-memory decryption.

---

## 2. Target Personas

### Persona A: Privacy-Conscious Freelancer ("Maya")
- **Needs**: Stores contracts, tax invoices, and client NDAs. Wants a personal private cloud accessible on home Wi-Fi.
- **Pain Points**: Reluctant to trust public cloud providers (Google Drive, Dropbox) with confidential client files; lacks enterprise IT infrastructure.
- **Expectation**: Seamless drag-and-drop upload, verified file integrity on download, transparent encryption.

### Persona B: Technical Student / Researcher ("Alex")
- **Needs**: Stores research papers (PDFs), notes, and source code. Wants to query documents locally using an AI assistant.
- **Pain Points**: Cloud AI services train on user data or log search queries. Alex needs offline question answering that cites exact sources.
- **Expectation**: Fast keyword search on Free tier; accurate cited document Q&A on Premium tier without system crashes.

---

## 3. Subscription Model & Entitlements

CipherQ establishes two distinct subscription experiences. **Security protections are identical across both tiers**; the tiers differ strictly by storage capacity and compute-intensive AI capabilities.

| Feature Area | FREE Plan | PREMIUM Plan | Backend Enforcement Mechanism |
| :--- | :--- | :--- | :--- |
| **Storage Quota** | **1 GB** (Hypothesis) | **5 GB** (Hypothesis) | Pre-upload stream validation; rejects payload with `413 Payload Too Large` if user quota exceeded |
| **Encryption Standard** | Vetted Streaming AEAD (per-file DEK) | Vetted Streaming AEAD (per-file DEK) | Parity: Every file is encrypted before persistent disk write |
| **File Operations** | Upload, Download, Rename, Delete | Upload, Download, Rename, Delete | Authorized strictly against authenticated user session |
| **Search Engine** | **SQLite FTS5 Keyword Search** | **Semantic Vector Search + AI Q&A** | Server validates tier on `/api/ai/*` routes; returns `403 Forbidden` to Free users |
| **AI Query Allowance** | 0 queries/month | Up to 100 queries/day (rate limited) | Tracked in `usage_records` table; enforces bounded concurrency (max 1 concurrent query) |
| **UI Experience** | Standard Dashboard & Vault | Premium Badge, AI Chat Tab, Semantic Excerpts | Frontend renders tier status; backend independently verifies all requests |

---

## 4. Functional Specifications

### 4.1 Authentication & Session Management
- **Registration**: Email and passphrase. Passphrase hashed using **Argon2id** (`t_cost=3`, `m_cost=65536`, `p_cost=4`).
- **Login & Sessions**:
  - Issues cryptographically random session token (32 bytes urlsafe) stored hashed in SQLite.
  - Session transmitted via secure, HTTP-only, `SameSite=Lax` cookie.
  - Session timeout: 24-hour idle expiration.
- **CSRF Defense**: Double-submit or header-based token (`X-CSRF-Token`) validated on all mutating requests (`POST`, `PATCH`, `DELETE`).
- **Logout**: Immediate session revocation in database and cookie clearing.

### 4.2 File Management & Vault Lifecycle
- **Supported Formats**: `.pdf`, `.txt`, `.png`, `.jpg`, `.jpeg`, `.csv`, `.md`, and generic binary files.
- **Upload Flow**:
  1. Frontend streams file chunk-by-chunk to `POST /api/files`.
  2. Backend validates active quota and sanitizes filename (path traversal prevention).
  3. Server generates 256-bit random DEK and streams encrypted chunks into a temporary `.tmp` file using vetted streaming AEAD.
  4. Server calculates SHA-256 of plaintext on the fly.
  5. Upon successful completion, `.tmp` file is atomically renamed to `{file_id}.cqenc`.
- **Download Flow**:
  1. Client requests `GET /api/files/{id}/download`.
  2. Backend authorizes ownership.
  3. Server unwraps file DEK using Master KEK, verifies chunk AEAD tags, and streams decrypted chunks directly to client response.
- **Safe Recoverable Deletion**:
  1. User initiates deletion (`DELETE /api/files/{id}`).
  2. File status transitions to `PENDING_DELETION` (instantly hidden from listings).
  3. Task inserted into persistent `cleanup_queue` table.
  4. Cleanup worker unlinks ciphertext from disk, purges persistent AI chunks from SQLite, and marks job `COMPLETED`.

### 4.3 On-Demand Local AI Pipeline
- **Trigger**: AI extraction is **on-demand only**. Uploading a file does NOT automatically trigger resource-heavy extraction.
- **Text Extraction**: In-memory decryption; extracts text from `.txt` and `.pdf` files.
- **Chunking**: Sliding window (300 words with 50-word overlap).
- **Indexing & Search**:
  - Free users: Indexed into SQLite FTS5 for instant keyword search (~0MB RAM).
  - Premium users: Vector embeddings generated locally via lightweight ONNX CPU model (`all-MiniLM-L6-v2`, ~80MB RAM).
- **AI Document Q&A**:
  - Retrieval-Augmented Generation (RAG) with strict source attribution: `[Source: document.pdf, Chunk #1]`.
  - Memory Guard: If free system RAM drops below 500MB, generative LLM is bypassed and search returns direct cited excerpts.

---

## 5. Non-Functional & Operational Requirements

1. **Memory Budget**:
   - Backend baseline (idle): `< 150 MB RAM`.
   - Streaming file transfer overhead: bounded buffer (`< 1 MB RAM` process delta during transfer).
   - Peak AI processing: `< 2.5 GB RAM` total system memory, leaving `>= 1.5 GB` for Debian OS and system buffers on the 4GB UNO Q.
2. **Serving Architecture**:
   - Initial laptop prototype: Same-origin FastAPI hosting static frontend assets at `/` and API at `/api/v1/` on port `8000`.
   - Production UNO Q: Same-origin service with local TLS reverse proxy or secure private tunnel.
3. **Auditability**:
   - Every file transfer, authentication event, and deletion task produces an audit log entry without logging plaintext contents or cryptographic keys.
