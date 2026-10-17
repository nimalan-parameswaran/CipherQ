"""
CipherQ File Management API Router
Implements authenticated streaming upload, download with decryption,
file listing with ownership isolation, quota checks, and recoverable deletion via cleanup_queue.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Response, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.future import select

from backend.app.core.config import settings
from backend.app.core.key_manager import key_manager
from backend.app.db.session import get_db
from backend.app.db.models import User, FileRecord, CleanupQueue, UsageRecord
from backend.app.schemas.files import FileResponse, FileListResponse, FileDeleteResponse
from backend.app.api.deps import get_current_user, verify_csrf
from backend.app.services.vault import (
    vault_service,
    wrap_dek,
    unwrap_dek,
    sanitize_filename,
    QuotaExceededError,
    VaultIntegrityError
)
from backend.app.services.entitlements import (
    entitlement_service,
    QuotaExceededError as EntitlementQuotaExceeded,
    DiskSpaceExhaustedError
)

router = APIRouter(prefix="/files", tags=["Files"])


def get_user_quota(user: User) -> int:
    """Return maximum allowed storage bytes based on subscription tier."""
    return entitlement_service.get_user_quota(user)


@router.post("", response_model=FileResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream upload directly to the encrypted vault.
    Enforces storage quotas, generates a per-file DEK, wraps DEK with Master KEK,
    and performs atomic file staging with concurrency protection.
    """
    # 1. Check current storage utilization
    stmt = select(UsageRecord).where(UsageRecord.user_id == current_user.id)
    usage = (await db.execute(stmt)).scalar_one_or_none()
    current_bytes = usage.storage_bytes_used if usage else 0
    quota_bytes = get_user_quota(current_user)

    # Fast rejection if already at or over quota (e.g. after a downgrade)
    if current_bytes >= quota_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Storage quota exceeded. Your current usage ({current_bytes} bytes) meets or exceeds your {current_user.plan_type} plan quota ({quota_bytes} bytes). Delete files to regain upload capacity."
        )

    # Check file size hint if available on UploadFile
    file_size_hint = getattr(file, "size", None)

    file_id = str(uuid.uuid4())
    safe_name = sanitize_filename(file.filename or "untitled")
    mime_type = file.content_type or "application/octet-stream"

    # 2. Generate per-file DEK and wrap with Master KEK
    file_dek = vault_service.generate_file_dek()
    master_kek = key_manager.load_master_key()
    wrapped_dek = wrap_dek(file_dek, master_kek)

    # 3. Stream encrypt directly to disk guarded by InFlightQuotaTracker
    try:
        async with entitlement_service.tracker.track_upload(
            user_id=current_user.id,
            current_committed_bytes=current_bytes,
            quota_bytes=quota_bytes,
            content_length=file_size_hint
        ):
            remaining_bytes = max(0, quota_bytes - current_bytes)
            storage_name, file_size, sha256_hash = await vault_service.encrypt_stream_to_vault(
                file_id=file_id,
                upload_stream=file,
                dek=file_dek,
                max_allowed_bytes=remaining_bytes
            )
    except (QuotaExceededError, EntitlementQuotaExceeded) as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(e)
        )
    except DiskSpaceExhaustedError as e:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File encryption failed: {e}"
        )

    # 4. Atomic verification at commit time
    # Check if a concurrent request completed during streaming and exhausted the remaining quota
    stmt_recheck = select(UsageRecord).where(UsageRecord.user_id == current_user.id)
    usage = (await db.execute(stmt_recheck)).scalar_one_or_none()
    fresh_bytes = usage.storage_bytes_used if usage else 0
    if fresh_bytes + file_size > quota_bytes:
        vault_service.delete_vault_file(storage_name)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Storage quota exceeded during concurrent upload. Plan limit is {quota_bytes} bytes."
        )

    # 5. Save metadata to database
    file_record = FileRecord(
        id=file_id,
        user_id=current_user.id,
        original_name=safe_name,
        storage_name=storage_name,
        file_size_bytes=file_size,
        mime_type=mime_type,
        sha256_hash=sha256_hash,
        wrapped_dek=wrapped_dek,
        nonce_or_header=b"",
        status="ACTIVE",
        is_indexed=0
    )
    db.add(file_record)

    # Update usage
    if usage:
        usage.storage_bytes_used += file_size
    else:
        usage = UsageRecord(user_id=current_user.id, storage_bytes_used=file_size)
        db.add(usage)

    await db.commit()
    await db.refresh(file_record)

    return file_record


@router.get("", response_model=FileListResponse)
async def list_files(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all active encrypted files owned by the authenticated user."""
    stmt = (
        select(FileRecord)
        .where(FileRecord.user_id == current_user.id, FileRecord.status == "ACTIVE")
        .order_by(FileRecord.created_at.desc())
    )
    files = (await db.execute(stmt)).scalars().all()

    # Get usage info
    stmt_usage = select(UsageRecord).where(UsageRecord.user_id == current_user.id)
    usage = (await db.execute(stmt_usage)).scalar_one_or_none()
    storage_used = usage.storage_bytes_used if usage else 0
    quota = get_user_quota(current_user)

    return FileListResponse(
        files=[FileResponse.model_validate(f) for f in files],
        total_count=len(files),
        storage_bytes_used=storage_used,
        storage_quota_bytes=quota
    )


@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream and decrypt the requested file.
    Enforces strict user ownership: User A cannot access User B's files.
    """
    stmt = select(FileRecord).where(
        FileRecord.id == file_id,
        FileRecord.user_id == current_user.id,
        FileRecord.status == "ACTIVE"
    )
    file_record = (await db.execute(stmt)).scalar_one_or_none()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found or access denied."
        )

    # Unwrap DEK
    master_kek = key_manager.load_master_key()
    try:
        file_dek = unwrap_dek(file_record.wrapped_dek, master_kek)
    except VaultIntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cryptographic failure: {e}"
        )

    # Decrypt and stream chunks
    try:
        chunk_generator = vault_service.decrypt_vault_stream(
            file_id=file_record.id,
            storage_name=file_record.storage_name,
            dek=file_dek
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encrypted ciphertext missing from vault storage."
        )

    headers = {
        "Content-Disposition": f'attachment; filename="{file_record.original_name}"',
        "Content-Length": str(file_record.file_size_bytes)
    }

    return StreamingResponse(
        chunk_generator,
        media_type=file_record.mime_type,
        headers=headers
    )


@router.delete("/{file_id}", response_model=FileDeleteResponse)
async def delete_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db)
):
    """
    Initiate durable two-phase deletion workflow.
    Marks status PENDING_DELETION, records task in cleanup_queue,
    unlinks ciphertext from disk, and purges database metadata.
    """
    stmt = select(FileRecord).where(
        FileRecord.id == file_id,
        FileRecord.user_id == current_user.id,
        FileRecord.status == "ACTIVE"
    )
    file_record = (await db.execute(stmt)).scalar_one_or_none()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found or access denied."
        )

    # Phase 1: Soft-delete in database
    file_record.status = "PENDING_DELETION"
    storage_name = file_record.storage_name
    file_size = file_record.file_size_bytes

    # Queue durable cleanup task
    task = CleanupQueue(
        file_id=file_id,
        storage_path=storage_name,
        status="PENDING"
    )
    db.add(task)
    await db.flush()

    # Decrement storage usage
    stmt_usage = select(UsageRecord).where(UsageRecord.user_id == current_user.id)
    usage = (await db.execute(stmt_usage)).scalar_one_or_none()
    if usage:
        usage.storage_bytes_used = max(0, usage.storage_bytes_used - file_size)

    # Phase 2: Unlink physical file from vault
    success = vault_service.delete_vault_file(storage_name)
    if success:
        task.status = "COMPLETED"
        await db.execute(text("DELETE FROM file_chunks_fts WHERE file_id = :file_id"), {"file_id": file_id})
        await db.delete(file_record)
    else:
        task.status = "FAILED"
        task.last_error = "Could not remove file from disk; will retry on startup."

    await db.commit()

    return FileDeleteResponse(
        message="File removed from vault.",
        file_id=file_id,
        task_id=task.task_id,
        status=task.status
    )
