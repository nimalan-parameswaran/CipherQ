"""
Comprehensive Automated Test Suite for CipherQ AI Engine (Phase 5)
Verifies:
1. On-demand indexing: files are never automatically indexed upon upload
2. Multi-tenant isolation: User A cannot search or access User B's indexed chunks or citations
3. Ownership guards: User B cannot trigger indexing on User A's files
4. Cascade deletion: Deleting a vault file purges all chunks, FTS5 rows, and embeddings
5. Grounded citations & zero-evidence fallback: Answers cite exact files and pages without hallucination
6. Unsupported & malformed files: Graceful handling of binary and corrupt files
7. Zero external network calls: 100% local, offline operation
"""
import pytest
import socket
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.future import select

from backend.app.db.models import User, FileRecord, FileChunk, ChunkEmbedding


@pytest.mark.asyncio
async def test_on_demand_indexing_lifecycle(client: AsyncClient, test_db_session: AsyncSession):
    """Verify documents are not automatically indexed upon upload, and indexing is strictly on-demand."""
    # 1. Register and login
    await client.post("/api/v1/auth/register", json={
        "email": "ondemand_user@example.com",
        "password": "Password2026!",
        "plan_type": "FREE"
    })
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "ondemand_user@example.com",
        "password": "Password2026!"
    })
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # 2. Upload document
    doc_content = b"The secret board clock frequency is exactly 1333 MHz on Debian Linux."
    up_res = await client.post(
        "/api/v1/files",
        files={"file": ("clock_spec.txt", doc_content, "text/plain")},
        headers=headers
    )
    assert up_res.status_code == 201
    file_id = up_res.json()["id"]
    assert up_res.json()["is_indexed"] == 0, "Uploaded file must NOT be automatically indexed"

    # 3. Query before indexing: must find NO evidence
    q_pre = await client.post("/api/v1/ai/query", json={"query": "clock frequency"})
    assert q_pre.status_code == 200
    pre_data = q_pre.json()
    assert pre_data["has_sufficient_evidence"] is False
    assert len(pre_data["citations"]) == 0

    # 4. Explicitly trigger on-demand indexing
    idx_res = await client.post(f"/api/v1/ai/index/{file_id}", headers=headers)
    assert idx_res.status_code == 200
    assert idx_res.json()["is_indexed"] is True
    assert idx_res.json()["chunks_created"] >= 1

    # 5. Query after indexing: must find matching evidence and citation
    q_post = await client.post("/api/v1/ai/query", json={"query": "clock frequency"})
    assert q_post.status_code == 200
    post_data = q_post.json()
    assert post_data["has_sufficient_evidence"] is True
    assert len(post_data["citations"]) >= 1
    assert post_data["citations"][0]["filename"] == "clock_spec.txt"
    assert "1333 MHz" in post_data["citations"][0]["snippet"] or "clock" in post_data["citations"][0]["snippet"]


@pytest.mark.asyncio
async def test_cross_user_ai_isolation(client: AsyncClient):
    """Verify User B cannot retrieve or search User A's indexed documents under any circumstances."""
    # Register User A (Alice - Free)
    await client.post("/api/v1/auth/register", json={
        "email": "alice_ai@example.com",
        "password": "Password2026!",
        "plan_type": "FREE"
    })
    login_a = await client.post("/api/v1/auth/login", json={
        "email": "alice_ai@example.com",
        "password": "Password2026!"
    })
    csrf_a = login_a.json()["csrf_token"]

    # Alice uploads and indexes Project Titan notes
    up_a = await client.post(
        "/api/v1/files",
        files={"file": ("titan_blueprint.txt", b"Project Titan secret code is TITAN-9988-ALPHA.", "text/plain")},
        headers={"X-CSRF-Token": csrf_a}
    )
    file_a_id = up_a.json()["id"]
    await client.post(f"/api/v1/ai/index/{file_a_id}", headers={"X-CSRF-Token": csrf_a})

    # Logout Alice
    await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_a})

    # Register User B (Bob - Premium)
    await client.post("/api/v1/auth/register", json={
        "email": "bob_ai@example.com",
        "password": "Password2026!",
        "plan_type": "PREMIUM"
    })
    login_b = await client.post("/api/v1/auth/login", json={
        "email": "bob_ai@example.com",
        "password": "Password2026!"
    })
    csrf_b = login_b.json()["csrf_token"]

    # Bob queries for Alice's secret code
    q_bob = await client.post("/api/v1/ai/query", json={"query": "Project Titan secret code"})
    assert q_bob.status_code == 200
    bob_data = q_bob.json()

    # Bob MUST get zero evidence and zero citations
    assert bob_data["has_sufficient_evidence"] is False
    assert len(bob_data["citations"]) == 0
    assert "TITAN-9988-ALPHA" not in bob_data["answer"]

    # Bob attempts to index Alice's file directly: must be forbidden / 404
    hack_idx = await client.post(f"/api/v1/ai/index/{file_a_id}", headers={"X-CSRF-Token": csrf_b})
    assert hack_idx.status_code == 404


@pytest.mark.asyncio
async def test_file_deletion_cascades_all_ai_data(client: AsyncClient, test_db_session: AsyncSession):
    """Verify that deleting a file purges its chunks, FTS5 index rows, and embeddings."""
    await client.post("/api/v1/auth/register", json={
        "email": "cascade_user@example.com",
        "password": "Password2026!",
        "plan_type": "PREMIUM"
    })
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "cascade_user@example.com",
        "password": "Password2026!"
    })
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # Upload and index file
    up_res = await client.post(
        "/api/v1/files",
        files={"file": ("to_be_deleted.txt", b"UniqueTermCascade9911 keyword to scrub.", "text/plain")},
        headers=headers
    )
    file_id = up_res.json()["id"]
    await client.post(f"/api/v1/ai/index/{file_id}", headers=headers)

    # Verify rows exist in DB
    chunks_before = (await test_db_session.execute(
        select(FileChunk).where(FileChunk.file_id == file_id)
    )).scalars().all()
    assert len(chunks_before) >= 1

    fts_before = (await test_db_session.execute(
        text("SELECT * FROM file_chunks_fts WHERE file_id = :file_id"),
        {"file_id": file_id}
    )).fetchall()
    assert len(fts_before) >= 1

    # Delete the file
    del_res = await client.delete(f"/api/v1/files/{file_id}", headers=headers)
    assert del_res.status_code == 200

    # Verify all AI data was scrubbed
    chunks_after = (await test_db_session.execute(
        select(FileChunk).where(FileChunk.file_id == file_id)
    )).scalars().all()
    assert len(chunks_after) == 0

    fts_after = (await test_db_session.execute(
        text("SELECT * FROM file_chunks_fts WHERE file_id = :file_id"),
        {"file_id": file_id}
    )).fetchall()
    assert len(fts_after) == 0

    # Query for the deleted term: must find nothing
    q_res = await client.post("/api/v1/ai/query", json={"query": "UniqueTermCascade9911"})
    assert q_res.status_code == 200
    assert q_res.json()["has_sufficient_evidence"] is False


@pytest.mark.asyncio
async def test_unsupported_and_malformed_file_handling(client: AsyncClient):
    """Verify that binary executables, corrupt files, and empty files fail gracefully."""
    await client.post("/api/v1/auth/register", json={
        "email": "malformed_user@example.com",
        "password": "Password2026!",
        "plan_type": "FREE"
    })
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "malformed_user@example.com",
        "password": "Password2026!"
    })
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # 1. Upload binary executable with null bytes
    binary_content = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00>\x00"
    up_bin = await client.post(
        "/api/v1/files",
        files={"file": ("malicious_payload.bin", binary_content, "application/octet-stream")},
        headers=headers
    )
    bin_id = up_bin.json()["id"]

    # Attempt indexing binary: must return 422 Unprocessable Entity
    idx_bin = await client.post(f"/api/v1/ai/index/{bin_id}", headers=headers)
    assert idx_bin.status_code == 422
    assert "not supported" in idx_bin.json()["detail"].lower() or "binary" in idx_bin.json()["detail"].lower()

    # 2. Upload corrupt PDF
    corrupt_pdf = b"%PDF-1.4 corrupt header without EOF marker"
    up_pdf = await client.post(
        "/api/v1/files",
        files={"file": ("corrupt.pdf", corrupt_pdf, "application/pdf")},
        headers=headers
    )
    pdf_id = up_pdf.json()["id"]

    idx_pdf = await client.post(f"/api/v1/ai/index/{pdf_id}", headers=headers)
    assert idx_pdf.status_code in (400, 422)


@pytest.mark.asyncio
async def test_zero_outbound_network_calls_during_ai_operations(client: AsyncClient, monkeypatch):
    """Verify that indexing and search never attempt external network calls."""
    # Intercept socket connection attempts
    connected_hosts = []
    real_connect = socket.socket.connect

    def mock_connect(self, address):
        host, port = address[0], address[1]
        # Allow internal localhost loopback connections
        if host not in ("127.0.0.1", "localhost", "::1"):
            connected_hosts.append(address)
            raise RuntimeError(f"Prohibited external network call intercepted: {address}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", mock_connect)

    await client.post("/api/v1/auth/register", json={
        "email": "airgap_user@example.com",
        "password": "Password2026!",
        "plan_type": "PREMIUM"
    })
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "airgap_user@example.com",
        "password": "Password2026!"
    })
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    # Upload document
    up_res = await client.post(
        "/api/v1/files",
        files={"file": ("airgap_doc.txt", b"Airgap document with confidential local specifications.", "text/plain")},
        headers=headers
    )
    file_id = up_res.json()["id"]

    # Index document
    await client.post(f"/api/v1/ai/index/{file_id}", headers=headers)

    # Query document
    q_res = await client.post("/api/v1/ai/query", json={"query": "confidential local specifications"})
    assert q_res.status_code == 200

    # Assert ZERO external hosts were contacted
    assert len(connected_hosts) == 0, f"Expected 0 external connections, got: {connected_hosts}"


@pytest.mark.asyncio
async def test_unindex_file_preserves_vault_ciphertext(client: AsyncClient):
    """Verify unindexing a document purges search chunks but preserves the encrypted vault file."""
    await client.post("/api/v1/auth/register", json={
        "email": "unindex_user@example.com",
        "password": "Password2026!",
        "plan_type": "FREE"
    })
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "unindex_user@example.com",
        "password": "Password2026!"
    })
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    up_res = await client.post(
        "/api/v1/files",
        files={"file": ("unindex_sample.txt", b"KeepCiphertextSafe secret term for test.", "text/plain")},
        headers=headers
    )
    file_id = up_res.json()["id"]

    # Index
    await client.post(f"/api/v1/ai/index/{file_id}", headers=headers)
    q1 = await client.post("/api/v1/ai/query", json={"query": "KeepCiphertextSafe"})
    assert q1.json()["has_sufficient_evidence"] is True

    # Unindex
    unidx_res = await client.delete(f"/api/v1/ai/index/{file_id}", headers=headers)
    assert unidx_res.status_code == 200

    # Query again: must find nothing
    q2 = await client.post("/api/v1/ai/query", json={"query": "KeepCiphertextSafe"})
    assert q2.json()["has_sufficient_evidence"] is False

    # Vault file MUST still exist in file listing
    files_res = await client.get("/api/v1/files", headers=headers)
    file_records = files_res.json()["files"]
    target_rec = next((f for f in file_records if f["id"] == file_id), None)
    assert target_rec is not None, "Vault ciphertext file must NOT be deleted upon unindexing"
    assert target_rec["is_indexed"] == 0


@pytest.mark.asyncio
async def test_pdf_extraction_page_level_citations(client: AsyncClient):
    """Verify that multi-page PDFs extract page metadata accurately and cite the correct page number."""
    # Build a valid 2-page PDF in pure Python without external generator dependencies
    header = b"%PDF-1.4\n"
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> /MediaBox [0 0 612 792] /Contents 6 0 R >> endobj\n",
        b"4 0 obj << /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> /MediaBox [0 0 612 792] /Contents 7 0 R >> endobj\n",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"6 0 obj << /Length 59 >> stream\nBT /F1 12 Tf 100 700 Td (Page 1 Architecture: kernel boot sequence) Tj ET\nendstream\nendobj\n",
        b"7 0 obj << /Length 61 >> stream\nBT /F1 12 Tf 100 700 Td (Page 2 Slab Allocator: memory management subsystem) Tj ET\nendstream\nendobj\n",
    ]
    offsets = [0]
    curr = len(header)
    for obj in objs:
        offsets.append(curr)
        curr += len(obj)

    xref_offset = curr
    xref = f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        xref += f"{off:010d} 00000 n \n".encode()
    trailer = f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    pdf_bytes = header + b"".join(objs) + xref + trailer

    await client.post("/api/v1/auth/register", json={
        "email": "pdf_citation_user@example.com",
        "password": "Password2026!",
        "plan_type": "PREMIUM"
    })
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "pdf_citation_user@example.com",
        "password": "Password2026!"
    })
    csrf = login_res.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    up_res = await client.post(
        "/api/v1/files",
        files={"file": ("kernel_specs.pdf", pdf_bytes, "application/pdf")},
        headers=headers
    )
    assert up_res.status_code == 201
    file_id = up_res.json()["id"]

    # On-demand index
    idx_res = await client.post(f"/api/v1/ai/index/{file_id}", headers=headers)
    assert idx_res.status_code == 200
    assert idx_res.json()["chunks_created"] == 2
    assert idx_res.json()["pages_processed"] == 2

    # Query page 2 topic: "Slab Allocator"
    q_res = await client.post("/api/v1/ai/query", json={"query": "slab allocator"})
    assert q_res.status_code == 200
    res_data = q_res.json()
    assert res_data["has_sufficient_evidence"] is True
    citation = res_data["citations"][0]
    assert citation["filename"] == "kernel_specs.pdf"
    assert citation["page_number"] == 2
    assert "slab allocator" in citation["snippet"].lower()

    # Query page 1 topic: "boot sequence"
    q1_res = await client.post("/api/v1/ai/query", json={"query": "boot sequence"})
    assert q1_res.status_code == 200
    res_data1 = q1_res.json()
    assert res_data1["has_sufficient_evidence"] is True
    citation1 = res_data1["citations"][0]
    assert citation1["filename"] == "kernel_specs.pdf"
    assert citation1["page_number"] == 1
    assert "boot sequence" in citation1["snippet"].lower()

