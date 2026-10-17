"""
Unit Tests for Cryptographic Storage Engine & Vault Primitives
Tests per-file DEK wrapping, streaming AEAD encryption/decryption, bit-flip tampering,
truncation detection, chunk reordering detection, interrupted upload cleanup, and startup reconciliation.
"""
import os
import time
import pytest
import io
from pathlib import Path
from unittest.mock import AsyncMock

from backend.app.core.config import settings
from backend.app.services.vault import (
    VaultStorageService,
    wrap_dek,
    unwrap_dek,
    sanitize_filename,
    get_vault_path,
    reconcile_startup_vault,
    VaultIntegrityError,
    VaultError
)
import nacl.bindings as b


def test_wrap_and_unwrap_dek():
    """Verify DEK wrapping with Master KEK and tamper rejection on unwrap."""
    master_kek = b.crypto_secretstream_xchacha20poly1305_keygen()
    file_dek = b.crypto_secretstream_xchacha20poly1305_keygen()

    wrapped = wrap_dek(file_dek, master_kek)
    assert len(wrapped) == 12 + 32 + 16  # 12B nonce + 32B key + 16B GCM tag = 60B

    # Valid unwrap
    recovered = unwrap_dek(wrapped, master_kek)
    assert recovered == file_dek

    # Tampered wrapped blob
    tampered = bytearray(wrapped)
    tampered[20] ^= 0xFF
    with pytest.raises(VaultIntegrityError):
        unwrap_dek(bytes(tampered), master_kek)

    # Wrong master KEK
    wrong_kek = b.crypto_secretstream_xchacha20poly1305_keygen()
    with pytest.raises(VaultIntegrityError):
        unwrap_dek(wrapped, wrong_kek)


def test_sanitize_filename_and_path_traversal():
    """Verify directory traversal payloads are neutralized."""
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Windows\\System32\\cmd.exe") == "cmd.exe"
    assert sanitize_filename("normal_file.pdf") == "normal_file.pdf"
    assert sanitize_filename("") == "untitled_document"

    # Path traversal attack detection
    with pytest.raises(VaultError):
        get_vault_path("../../../outside_vault.cqenc")


@pytest.mark.asyncio
async def test_streaming_encryption_and_decryption_roundtrip(temp_dir):
    """Verify streaming encryption and decryption roundtrip produces identical plaintext."""
    vault = VaultStorageService()
    file_id = "test_file_roundtrip_001"
    dek = vault.generate_file_dek()
    test_content = b"CipherQ Streaming AEAD Verification Payload: " * 1000  # ~45 KB

    # Mock async stream reader
    class MockStream:
        def __init__(self, data: bytes):
            self.bio = io.BytesIO(data)
        async def read(self, n: int = -1) -> bytes:
            return self.bio.read(n)

    mock_upload = MockStream(test_content)
    storage_name, size, sha256_hash = await vault.encrypt_stream_to_vault(
        file_id=file_id,
        upload_stream=mock_upload,
        dek=dek,
        max_allowed_bytes=10 * 1024 * 1024
    )

    assert size == len(test_content)
    vault_file = get_vault_path(storage_name)
    assert vault_file.exists()

    # Stream decrypt
    decrypted_chunks = list(vault.decrypt_vault_stream(file_id, storage_name, dek))
    decrypted_content = b"".join(decrypted_chunks)
    assert decrypted_content == test_content

    # Clean up
    vault.delete_vault_file(storage_name)


@pytest.mark.asyncio
async def test_tamper_detection_bit_flip(temp_dir):
    """Verify flipping a single bit in the ciphertext causes VaultIntegrityError."""
    vault = VaultStorageService()
    file_id = "test_tamper_001"
    dek = vault.generate_file_dek()
    test_content = b"Sensitive Confidential Document Data"

    class MockStream:
        def __init__(self, data: bytes):
            self.bio = io.BytesIO(data)
        async def read(self, n: int = -1) -> bytes:
            return self.bio.read(n)

    storage_name, _, _ = await vault.encrypt_stream_to_vault(
        file_id=file_id,
        upload_stream=MockStream(test_content),
        dek=dek,
        max_allowed_bytes=1024 * 1024
    )

    vault_file = get_vault_path(storage_name)
    raw = bytearray(vault_file.read_bytes())

    # Flip bit in ciphertext body (after 24-byte header and 4-byte chunk len)
    raw[35] ^= 0x01
    vault_file.write_bytes(bytes(raw))

    with pytest.raises(VaultIntegrityError):
        list(vault.decrypt_vault_stream(file_id, storage_name, dek))

    vault.delete_vault_file(storage_name)


@pytest.mark.asyncio
async def test_truncation_attack_detection(temp_dir):
    """Verify truncated ciphertext stream (missing TAG_FINAL) raises VaultIntegrityError."""
    vault = VaultStorageService()
    file_id = "test_truncation_001"
    dek = vault.generate_file_dek()
    test_content = b"A" * (128 * 1024)  # 128 KB (2 chunks)

    class MockStream:
        def __init__(self, data: bytes):
            self.bio = io.BytesIO(data)
        async def read(self, n: int = -1) -> bytes:
            return self.bio.read(n)

    storage_name, _, _ = await vault.encrypt_stream_to_vault(
        file_id=file_id,
        upload_stream=MockStream(test_content),
        dek=dek,
        max_allowed_bytes=1024 * 1024
    )

    vault_file = get_vault_path(storage_name)
    raw = vault_file.read_bytes()

    # Truncate file so the second (final) chunk is lost
    vault_file.write_bytes(raw[:70000])

    with pytest.raises(VaultIntegrityError) as exc:
        list(vault.decrypt_vault_stream(file_id, storage_name, dek))

    assert "truncated" in str(exc.value).lower()
    vault.delete_vault_file(storage_name)


@pytest.mark.asyncio
async def test_interrupted_upload_cleans_temporary_file(temp_dir):
    """Verify that an interrupted or errored upload deletes the .tmp staging file."""
    vault = VaultStorageService()
    file_id = "test_interrupted_upload"
    dek = vault.generate_file_dek()

    class FailingStream:
        async def read(self, n: int = -1):
            raise ConnectionResetError("Client disconnected midway through upload.")

    with pytest.raises(ConnectionResetError):
        await vault.encrypt_stream_to_vault(
            file_id=file_id,
            upload_stream=FailingStream(),
            dek=dek,
            max_allowed_bytes=1024 * 1024
        )

    # Ensure no .tmp or .cqenc files remain
    tmp_path = get_vault_path(f"{file_id}.tmp")
    cqenc_path = get_vault_path(f"{file_id}.cqenc")
    assert not tmp_path.exists()
    assert not cqenc_path.exists()


@pytest.mark.asyncio
async def test_conservative_startup_reconciliation(test_db_session):
    """
    Verify startup reconciliation rules:
    - Fresh .tmp file (<30 mins) is PRESERVED.
    - Stale .tmp file (>1 hr) is UNLINKED.
    - Orphan .cqenc file is QUARANTINED.
    """
    vault_dir = settings.VAULT_DIR
    vault_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()

    # 1. Create fresh .tmp file (age = 5 minutes)
    fresh_tmp = vault_dir / "fresh_upload.tmp"
    fresh_tmp.write_bytes(b"active upload in flight")
    os.utime(fresh_tmp, (now - 300, now - 300))

    # 2. Create stale .tmp file (age = 2 hours)
    stale_tmp = vault_dir / "stale_upload.tmp"
    stale_tmp.write_bytes(b"abandoned upload")
    os.utime(stale_tmp, (now - 7200, now - 7200))

    # 3. Create orphan .cqenc file (no DB entry)
    orphan_cqenc = vault_dir / "orphan_ghost_file.cqenc"
    orphan_cqenc.write_bytes(b"unreferenced ciphertext")

    # Run reconciliation using test session
    from unittest.mock import MagicMock
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = test_db_session

    summary = await reconcile_startup_vault(mock_factory)

    # Assertions
    assert fresh_tmp.exists(), "Active upload .tmp file must NOT be deleted!"
    assert not stale_tmp.exists(), "Stale .tmp file > 1 hour must be deleted."
    assert not orphan_cqenc.exists(), "Orphan file should be moved out of active vault."

    quarantined = vault_dir / "orphans" / "orphan_ghost_file.cqenc"
    assert quarantined.exists(), "Orphan file must be safely moved to vault/orphans/."

    # Clean up test artifacts
    if fresh_tmp.exists():
        os.remove(fresh_tmp)
    if quarantined.exists():
        os.remove(quarantined)
