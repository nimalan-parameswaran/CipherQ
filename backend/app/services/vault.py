"""
CipherQ Cryptographic Vault Service
Implements per-file DEK generation, wrapping under Master KEK (AES-256-GCM),
and streaming authenticated encryption/decryption using PyNaCl libsodium secretstream (XChaCha20-Poly1305).
Strictly enforces bounded memory usage (< 1MB RAM delta) during file transfers.
"""
import os
import hashlib
import secrets
from pathlib import Path
from typing import AsyncGenerator, Generator, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import nacl.bindings as b

from backend.app.core.config import settings
from backend.app.core.key_manager import key_manager

CHUNK_SIZE = 64 * 1024  # 64 KB streaming blocks


class VaultError(Exception):
    """Base exception for file vault operations."""
    pass


class VaultIntegrityError(VaultError):
    """Raised when ciphertext is corrupted, truncated, or tampered with."""
    pass


class QuotaExceededError(VaultError):
    """Raised when user storage quota is exceeded."""
    pass


def wrap_dek(dek: bytes, master_kek: bytes) -> bytes:
    """Wrap a 256-bit DEK using the Master KEK (AES-256-GCM). Returns 12B nonce + 48B ciphertext."""
    aesgcm = AESGCM(master_kek)
    nonce = secrets.token_bytes(12)
    wrapped = aesgcm.encrypt(nonce, dek, b"cipherq_dek_wrap")
    return nonce + wrapped


def unwrap_dek(wrapped_dek_blob: bytes, master_kek: bytes) -> bytes:
    """Unwrap a 256-bit DEK using the Master KEK. Raises VaultIntegrityError on tamper."""
    if len(wrapped_dek_blob) < 28:
        raise VaultIntegrityError("Wrapped DEK blob is truncated.")
    nonce = wrapped_dek_blob[:12]
    ciphertext = wrapped_dek_blob[12:]
    aesgcm = AESGCM(master_kek)
    try:
        return aesgcm.decrypt(nonce, ciphertext, b"cipherq_dek_wrap")
    except Exception as e:
        raise VaultIntegrityError("Failed to unwrap DEK: Master KEK mismatch or corrupt key metadata.") from e


def sanitize_filename(original_name: str) -> str:
    """Sanitize original filename to strip directory traversal characters."""
    filename = Path(original_name).name.strip()
    return filename if filename else "untitled_document"


def get_vault_path(storage_name: str) -> Path:
    """Resolve and validate that the target storage file stays strictly within VAULT_DIR."""
    target = (settings.VAULT_DIR / storage_name).resolve()
    vault_root = settings.VAULT_DIR.resolve()
    if not str(target).startswith(str(vault_root)):
        raise VaultError("Path traversal attack detected: target file is outside vault directory.")
    return target


class VaultStorageService:
    """Provides streaming authenticated encryption and decryption for vault files."""

    def __init__(self):
        settings.init_directories()

    def generate_file_dek(self) -> bytes:
        """Generate a cryptographically random 256-bit DEK for a new file."""
        return b.crypto_secretstream_xchacha20poly1305_keygen()

    async def encrypt_stream_to_vault(
        self,
        file_id: str,
        upload_stream,
        dek: bytes,
        max_allowed_bytes: int
    ) -> Tuple[str, int, str]:
        """
        Stream upload chunks directly into an encrypted file in the vault.
        Writes to .tmp file first; atomically renames to .cqenc on completion.
        Returns: (storage_name, file_size_bytes, sha256_hash).
        """
        storage_name = f"{file_id}.cqenc"
        final_path = get_vault_path(storage_name)
        tmp_path = final_path.with_suffix(".tmp")

        state = b.crypto_secretstream_xchacha20poly1305_state()
        header = b.crypto_secretstream_xchacha20poly1305_init_push(state, dek)
        ad = file_id.encode("utf-8")

        sha256 = hashlib.sha256()
        total_plaintext_bytes = 0

        try:
            with open(tmp_path, "wb") as f_out:
                # Write 24-byte secretstream header
                f_out.write(header)

                # Buffer one chunk ahead to accurately detect the final chunk
                prev_chunk = await upload_stream.read(CHUNK_SIZE)
                if not prev_chunk:
                    # Empty file edge case
                    ct = b.crypto_secretstream_xchacha20poly1305_push(
                        state, b"", ad, b.crypto_secretstream_xchacha20poly1305_TAG_FINAL
                    )
                    f_out.write(len(ct).to_bytes(4, "big") + ct)
                else:
                    while prev_chunk:
                        next_chunk = await upload_stream.read(CHUNK_SIZE)
                        is_last = (len(next_chunk) == 0)

                        total_plaintext_bytes += len(prev_chunk)
                        if total_plaintext_bytes > max_allowed_bytes:
                            raise QuotaExceededError(
                                f"File upload exceeds remaining storage quota ({max_allowed_bytes} bytes)."
                            )

                        sha256.update(prev_chunk)

                        tag = (
                            b.crypto_secretstream_xchacha20poly1305_TAG_FINAL
                            if is_last
                            else b.crypto_secretstream_xchacha20poly1305_TAG_MESSAGE
                        )

                        ct = b.crypto_secretstream_xchacha20poly1305_push(state, prev_chunk, ad, tag)
                        f_out.write(len(ct).to_bytes(4, "big") + ct)

                        prev_chunk = next_chunk

                f_out.flush()
                os.fsync(f_out.fileno())

            # Atomic staging: rename .tmp to .cqenc
            tmp_path.replace(final_path)

        except Exception:
            # Clean up temporary staging file on any error / disconnect
            if tmp_path.exists():
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise

        return storage_name, total_plaintext_bytes, sha256.hexdigest()

    def decrypt_vault_stream(
        self,
        file_id: str,
        storage_name: str,
        dek: bytes
    ) -> Generator[bytes, None, None]:
        """
        Yields decrypted plaintext chunks directly from the vault file for streaming download.
        Verifies authentication tag on every chunk; detects truncation and tampering.
        """
        vault_path = get_vault_path(storage_name)
        if not vault_path.exists():
            raise FileNotFoundError(f"Encrypted vault file {storage_name} not found on disk.")

        ad = file_id.encode("utf-8")
        header_len = b.crypto_secretstream_xchacha20poly1305_HEADERBYTES

        saw_final_tag = False

        with open(vault_path, "rb") as f_in:
            header = f_in.read(header_len)
            if len(header) < header_len:
                raise VaultIntegrityError("Ciphertext header is missing or truncated.")

            pull_state = b.crypto_secretstream_xchacha20poly1305_state()
            try:
                b.crypto_secretstream_xchacha20poly1305_init_pull(pull_state, header, dek)
            except Exception as e:
                raise VaultIntegrityError("Failed to initialize decryption: invalid header or DEK.") from e

            while True:
                len_bytes = f_in.read(4)
                if not len_bytes:
                    break

                chunk_len = int.from_bytes(len_bytes, "big")
                ciphertext_chunk = f_in.read(chunk_len)
                if len(ciphertext_chunk) < chunk_len:
                    raise VaultIntegrityError("Ciphertext stream truncated: chunk incomplete.")

                try:
                    plaintext, tag = b.crypto_secretstream_xchacha20poly1305_pull(
                        pull_state, ciphertext_chunk, ad
                    )
                except Exception as e:
                    raise VaultIntegrityError(
                        "Integrity check failed: ciphertext has been tampered with or modified."
                    ) from e

                if tag == b.crypto_secretstream_xchacha20poly1305_TAG_FINAL:
                    saw_final_tag = True

                yield plaintext

        if not saw_final_tag:
            raise VaultIntegrityError(
                "Truncation attack detected: stream terminated before final authenticated block."
            )

    def delete_vault_file(self, storage_name: str) -> bool:
        """Unlink encrypted file from disk. Returns True if deleted or already absent."""
        try:
            vault_path = get_vault_path(storage_name)
            if vault_path.exists():
                os.remove(vault_path)
            return True
        except Exception:
            return False


async def reconcile_startup_vault(session_factory) -> dict:
    """
    Conservative startup reconciliation:
    1. Active Upload Safety: Temporary files (.tmp) modified within the last 30 minutes are strictly preserved.
       Only stale .tmp files older than 1 hour are unlinked.
    2. Retryable Deletion Queue: Resumes pending/failed deletion tasks from cleanup_queue.
    3. Orphan Quarantine: Files on disk with no matching database record are safely moved to vault/orphans/.
    """
    import time
    from sqlalchemy.future import select
    from backend.app.db.models import CleanupQueue, FileRecord

    summary = {"stale_tmp_deleted": 0, "retried_cleanups": 0, "orphans_quarantined": 0}
    now = time.time()
    vault_dir = settings.VAULT_DIR
    orphans_dir = vault_dir / "orphans"

    # 1. Clean stale .tmp files (> 1 hour old; never touch < 30 mins)
    for entry in vault_dir.glob("*.tmp"):
        try:
            mtime = entry.stat().st_mtime
            age_sec = now - mtime
            if age_sec > 3600:  # > 1 hour old
                os.remove(entry)
                summary["stale_tmp_deleted"] += 1
        except Exception:
            pass

    # 2. Process CleanupQueue tasks
    async with session_factory() as db:
        stmt = select(CleanupQueue).where(CleanupQueue.status.in_(["PENDING", "FAILED"]))
        pending_tasks = (await db.execute(stmt)).scalars().all()

        for task in pending_tasks:
            success = vault_service.delete_vault_file(task.storage_path)
            if success:
                task.status = "COMPLETED"
                # Remove any lingering FileRecord
                stmt_f = select(FileRecord).where(FileRecord.id == task.file_id)
                f_rec = (await db.execute(stmt_f)).scalar_one_or_none()
                if f_rec:
                    await db.delete(f_rec)
                summary["retried_cleanups"] += 1
            else:
                task.retry_count += 1
                task.last_error = "Startup reconciliation: file still locked or missing."
        await db.commit()

    # 3. Check for orphan .cqenc files on disk
    async with session_factory() as db:
        stmt_active = select(FileRecord.storage_name).where(FileRecord.status == "ACTIVE")
        active_names = set((await db.execute(stmt_active)).scalars().all())

        for entry in vault_dir.glob("*.cqenc"):
            if entry.name not in active_names:
                orphans_dir.mkdir(parents=True, exist_ok=True)
                dest = orphans_dir / entry.name
                try:
                    entry.replace(dest)
                    summary["orphans_quarantined"] += 1
                except Exception:
                    pass

    return summary


vault_service = VaultStorageService()

