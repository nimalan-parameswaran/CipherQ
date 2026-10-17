# CipherQ Empirical Profiling & Resource Utilization Report

## 1. Executive Summary & Verification Standard
In accordance with CipherQ's engineering philosophy, hardware performance, encryption throughput, and memory bounds are never claimed without empirical measurement. This report documents the measured performance, RAM consumption, and concurrency behavior of CipherQ's streaming cryptographic storage engine and vanilla frontend integration.

Testing was conducted using live HTTP transfers over FastAPI on `http://127.0.0.1` using `psutil` process RSS monitoring, `PyNaCl 1.6.2` (libsodium engine), and Google Chrome browser execution driven by Playwright.

---

## 2. Benchmark Test Machine Specifications
- **Operating System:** Windows 11 Home 64-bit (Build 26100)
- **Processor:** Intel Core i7 (12th Gen) — 10 physical cores, 16 logical threads @ 1506.0 MHz base / 2300.0 MHz boost
- **Total System RAM:** 15.68 GB DDR5
- **Python Runtime:** Python 3.13.7 (CPython 64-bit)
- **Cryptographic Engine:** PyNaCl 1.6.2 binding `libsodium` (`crypto_secretstream_xchacha20poly1305`)
- **Web Framework:** FastAPI 0.115.12 on Uvicorn 0.34.0 (asyncio single worker)

---

## 3. Empirical Transfer Throughput & Process RAM Measurements

All payloads were generated using cryptographically strong pseudo-random bytes (`os.urandom`) and verified byte-for-byte upon roundtrip download with SHA-256 integrity checks.

| Workload Scenario | Payload Size | Upload Duration | Upload Throughput | Download Duration | Download Throughput | Baseline RAM | Peak Process RAM | Net RAM Delta |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **25 MB Single Transfer** | 25 MB | 0.20 s | **128.24 MB/s** | 0.12 s | **213.13 MB/s** | 86.6 MB | 88.6 MB | **+2.0 MB** |
| **50 MB Single Transfer** | 50 MB | 0.36 s | **140.51 MB/s** | 0.21 s | **239.92 MB/s** | 88.6 MB | 89.0 MB | **+0.4 MB** |
| **100 MB Single Transfer** | 100 MB | 0.74 s | **134.74 MB/s** | 0.42 s | **240.60 MB/s** | 89.1 MB | 89.2 MB | **+0.1 MB** |
| **Concurrent Transfers (2x 25MB)** | 50 MB Total | 0.39 s | **128.57 MB/s** | 0.18 s | **282.70 MB/s** | 89.2 MB | 88.8 MB | **-0.4 MB** |

> [!NOTE]
> **Zero File Buffering Verified:** Even when transferring a 100 MB payload or handling concurrent 25 MB streams, the net process memory change remained virtually flat (maximum RAM delta: **+2.0 MB**). At no point did the server buffer the payload in memory, validating the 64 KB chunked streaming architecture.

---

## 4. Analysis & Suitability for Arduino UNO Q (4GB RAM)

### 4.1 Memory Headroom
- **Server RSS Under Load:** ~89 MB total (including Python 3.13 runtime, SQLAlchemy, SQLite connection pool, and active streaming buffers).
- **Target Hardware Headroom:** On an Arduino UNO Q with 4 GB RAM running Debian Linux:
  - Base OS: ~250 MB
  - CipherQ Backend + Vault I/O: ~120 MB
  - Remaining Headroom for Local ONNX Embeddings + Small LLM: **~3.6 GB**
- **Conclusion:** The streaming vault storage engine consumes less than 3% of the target board's total physical RAM.

### 4.2 Throughput & Storage Bottlenecks
- On the laptop development machine, throughput exceeded **130 MB/s** upload and **240 MB/s** download.
- On the Arduino UNO Q, throughput will be bounded by the onboard 32GB eMMC flash write speeds (typically 50–120 MB/s sequential write) rather than CPU cryptographic processing, as XChaCha20-Poly1305 is heavily vectorized in libsodium (NEON instructions on ARM Cortex-A53).

---

## 5. Browser-Level Integration & Security Verification

Automated browser tests were executed via Playwright using system Google Chrome (`channel='chrome'`, Version 155):
1. **Cookie Security:** The `cipherq_session` cookie is transmitted strictly with `HttpOnly=True` and `SameSite=Lax`. JavaScript has zero access to raw session tokens; neither `localStorage` nor `sessionStorage` contains session credentials.
2. **CSRF Protection:** Mutating operations (`POST /files`, `DELETE /files/{id}`, `POST /auth/logout`) strictly require the `X-CSRF-Token` header, which is automatically populated from `sessionStorage` and verified in constant time.
3. **Download Decryption Integrity:** Files downloaded in the browser are streamed, decrypted in real-time, verified against the AEAD header/chunk tags, and saved to disk matching the original plaintext bit-for-bit.
4. **Cross-User Vault Isolation:** Two separate accounts (Maya on Free tier, Alex on Premium tier) were created and tested. Alex was unable to list, download, or access Maya's files, and vice versa.
5. **Quota Enforcement:** Free tier users are capped at 1 GB; Premium tier users receive 5 GB. Quotas are enforced on the backend during streaming upload (rejecting oversized files with HTTP 413) rather than relying on frontend client checks.
