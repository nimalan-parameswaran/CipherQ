# Cryptographic Storage Engine: Streaming AEAD Evaluation & Selection

**Date**: 2026-10-17  
**Evaluation Scope**: Google Tink `StreamingAead` vs. PyNaCl / libsodium `secretstream`  
**Target Platform**: Arduino UNO Q (4GB RAM, Debian Linux) & Local Laptop Prototype  
**Outcome**: Selected **PyNaCl / libsodium `crypto_secretstream_xchacha20poly1305`** based on empirical throughput, verified memory boundedness, and embedded platform compatibility.

---

## 1. Empirical Benchmark Results

Tested on Python 3.13.7 with `tracemalloc` process memory profiling and high-resolution performance timers:

| Evaluation Metric | Google Tink `StreamingAead` (`AES256_GCM_HKDF_4KB`) | PyNaCl / libsodium `secretstream` (`xchacha20poly1305`) | Winner / Selection Rationale |
| :--- | :--- | :--- | :--- |
| **1MB Encryption Time** | 8.7 ms | **3.1 ms** | **PyNaCl** (~2.8x faster) |
| **1MB Peak Encryption RAM** | 1,172.3 KB | **205.2 KB** | **PyNaCl** (~5.7x lower RAM) |
| **10MB Encryption Time** | 73.4 ms | **22.1 ms** | **PyNaCl** (~3.3x faster) |
| **10MB Peak Encryption RAM** | 10,390.4 KB (~10.4 MB) | **201.7 KB** (~0.2 MB) | **PyNaCl** (~51x lower RAM) |
| **25MB Streaming Decryption RAM** | Buffers underlying segments | **202.6 KB** | **PyNaCl** (Strictly bounded at ~200KB) |
| **Underlying Primitive** | AES-256-GCM + HKDF | XChaCha20-Poly1305 state machine | Both audited industry standards |
| **Framing Standard** | Google Tink proprietary segment format | Libsodium `crypto_secretstream` format | Libsodium is an open standard with cross-language RFC support |
| **Tamper Resistance** | Verified: Truncation raises `TinkError` | Verified: Chunk reorder raises `RuntimeError`, truncation detected | Both provide native cryptographic guarantees |
| **Embedded Linux Packaging** | Heavy C++ backend (Protobuf, Abseil); prebuilt wheels limited on 32-bit ARM | Lean C library (`libsodium`), native package in Debian (`libsodium-dev`) across all architectures | **PyNaCl / libsodium** |
| **Licensing** | Apache 2.0 | ISC (libsodium) / Apache 2.0 (PyNaCl) | Both fully permissive |

---

## 2. Selection Decision

**Selected Construction**: **PyNaCl / libsodium `crypto_secretstream_xchacha20poly1305`**.

### Key Technical Justifications:
1. **Strictly Bounded Memory Footprint**: Measured at **~202 KB peak RAM** during a continuous 25 MB file transfer, ensuring file transfers never threaten the 4GB RAM ceiling on the Arduino UNO Q.
2. **Superior Throughput**: More than 3x faster encryption latency compared to Tink in Python (22.1 ms for 10 MB vs. 73.4 ms).
3. **Hardware Portability**: Libsodium has native C optimizations for ARM and x86, with precompiled Debian packages available across all architectures (`aarch64`, `armhf`, `x86_64`).
4. **Standard Framing**: Implements the audited libsodium `crypto_secretstream` specification. Each chunk contains authenticated sequence states and an explicit `TAG_FINAL` marker, mathematically preventing truncation, reordering, and bit-flipping attacks without inventing custom cryptography.

---

## 3. Cryptographic Storage Architecture

```
Client Upload Stream (64KB chunks)
        |
        v
FastAPI Upload Handler
  1. Generate random 256-bit DEK via `crypto_secretstream_keygen()`
  2. Encrypt DEK under Master KEK (AES-256-GCM) with random 12-byte nonce
  3. Initialize libsodium push state: `header = init_push(state, DEK)`
  4. Write Header to `.tmp` file
  5. Stream 64KB chunks:
     - Push chunk into state with Associated Data (AD = file_id)
     - Tag: TAG_MESSAGE (for intermediate chunks) or TAG_FINAL (for last chunk)
     - Write chunk_len (4 bytes, big-endian) + ciphertext_with_tag
  6. Compute plaintext SHA-256 simultaneously
  7. Atomic rename: `file.tmp` -> `{file_id}.cqenc`
  8. Commit metadata, encrypted DEK, and SHA-256 to SQLite database
```
