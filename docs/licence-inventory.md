# CipherQ — Third-Party Licence & Asset Inventory

> **Policy**: CipherQ strictly incorporates open-source software, models, fonts, and assets with permissive licences (MIT, Apache 2.0, BSD, ISC, CC0, SIL OFL). Copyleft (GPL, AGPL) dependencies are prohibited unless explicitly reviewed and approved. No proprietary code, branding, or assets are copied.

---

## 1. Backend Core Dependencies (Python)

| Component Name | Exact Version (Tested / Pinned) | Source Repository / Homepage | SPDX Licence Identifier | Attribution & Notice Obligations | Redistribution & Usage Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FastAPI** | `0.115.0+` | https://github.com/fastapi/fastapi | `MIT` | Include MIT copyright notice | Permissive; standard web framework |
| **Starlette** | `0.48.0+` | https://github.com/encode/starlette | `BSD-3-Clause` | Include BSD 3-clause copyright notice | ASGI framework underlying FastAPI |
| **Uvicorn** | `0.38.0+` | https://github.com/encode/uvicorn | `BSD-3-Clause` | Include BSD 3-clause copyright notice | ASGI production web server |
| **Pydantic** | `2.12.3` | https://github.com/pydantic/pydantic | `MIT` | Include MIT copyright notice | Data parsing and validation |
| **Pydantic-Settings** | `2.11.0` | https://github.com/pydantic/pydantic-settings | `MIT` | Include MIT copyright notice | Environment configuration management |
| **SQLAlchemy** | `2.0.44` | https://github.com/sqlalchemy/sqlalchemy | `MIT` | Include MIT copyright notice | Database ORM and query builder |
| **aiosqlite** | `0.20.0+` | https://github.com/omnilib/aiosqlite | `MIT` | Include MIT copyright notice | Async SQLite interface |
| **argon2-cffi** | `25.1.0` | https://github.com/hynek/argon2-cffi | `MIT` | Include MIT copyright notice | Password hashing (wraps reference Argon2) |
| **cryptography** | `46.0.7` | https://github.com/pyca/cryptography | `Apache-2.0` OR `BSD-3-Clause` | Dual-licensed; include Apache-2.0 / BSD notice | OpenSSL / primitives provider |
| **Google Tink** | `1.16.1` | https://github.com/tink-crypto/tink-py | `Apache-2.0` | Include Apache 2.0 license notice & copyright | Streaming AEAD candidate (Google) |
| **PyNaCl** | `1.6.2` | https://github.com/pyca/pynacl | `Apache-2.0` | Include Apache 2.0 notice (wraps libsodium) | Streaming AEAD candidate (PyCA) |
| **libsodium** | *(bundled via PyNaCl)* | https://github.com/jedisct1/libsodium | `ISC` | Include ISC copyright notice | Underlying C cryptographic library |
| **psutil** | `7.2.2` | https://github.com/giampaolo/psutil | `BSD-3-Clause` | Include BSD 3-clause notice | System RAM & CPU resource monitoring |
| **pytest** | `8.4.2` | https://github.com/pytest-dev/pytest | `MIT` | Development dependency only | Automated testing framework |
| **httpx** | `0.27.0+` | https://github.com/encode/httpx | `BSD-3-Clause` | Development dependency only | Async HTTP testing client |

---

## 2. Transitive Dependencies Audit

| Transitive Component | Direct Parent | SPDX Licence | Notes & Flags |
| :--- | :--- | :--- | :--- |
| `cffi` | `argon2-cffi`, `pynacl`, `cryptography` | `MIT` | Permissive C-FFI wrapper |
| `pycparser` | `cffi` | `BSD-3-Clause` | Permissive C parser |
| `protobuf` | `tink` | `BSD-3-Clause` | Google Protocol Buffers runtime |
| `absl-py` | `tink` | `Apache-2.0` | Google Abseil Python utilities |
| `sniffio` | `anyio`, `httpx` | `Apache-2.0` OR `MIT` | Async I/O library detector |
| `typing_extensions` | `pydantic`, `fastapi` | `Python-2.0` (PSF) | Permissive typing backports |

---

## 3. Frontend Assets & UI Components

| Asset / Library | Version / Source | SPDX Licence | Origin & Verification |
| :--- | :--- | :--- | :--- |
| **Vanilla HTML5 / CSS3 / ES Modules** | N/A (Original Code) | `MIT` (Project License) | Written specifically for CipherQ; zero external framework dependencies |
| **System Typography Stack** | OS Native (-apple-system, Segoe UI, Roboto, Ubuntu, sans-serif) | System Provided | Zero font file bundling required; fully offline & accessible |
| **Icons (SVG)** | Derived from Lucide / Feather icon set | `ISC` / `MIT` | Clean, accessible inline SVGs; attribution maintained |

---

## 4. AI Models & Embedding Weights (Phase 5 Candidate Evaluation)

| Candidate Model | Intended Function | Upstream Provider & Source | Licence / Terms of Use | Compliance Notes & Constraints |
| :--- | :--- | :--- | :--- | :--- |
| **all-MiniLM-L6-v2 (ONNX)** | Semantic Search & Document Embeddings | Sentence-Transformers / Hugging Face | `Apache-2.0` | Highly permissive; runs locally on CPU with ~80MB RAM footprint |
| **Gemma 2 2B (GGUF Quantized)** | Local Document Q&A & Summarization | Google DeepMind / Hugging Face | **Gemma Terms of Use** | Open-weights model; permitted for commercial and research use subject to Gemma Prohibited Use Policy. No external API calls permitted. |
| **SQLite FTS5** | Keyword Search Baseline & Fallback | Built into SQLite engine | `Public Domain` / `Blessing` | Zero memory overhead; native full-text search fallback |

---

## 5. Licence Verification Log

- **Audit Date**: 2026-10-17
- **Checked By**: Antigravity Assistant & Project Maintainer
- **Status**: 100% of tested and selected packages hold permissive licenses (`MIT`, `Apache-2.0`, `BSD-3-Clause`, `ISC`). No GPL/AGPL copyleft contaminations detected in direct or transitive dependency trees.
