"""
CipherQ On-Demand Local AI API Router
Provides authenticated, ownership-isolated document indexing, FTS5 keyword search,
local semantic vector search, and grounded citation Q&A.
Zero cloud API transmission. Concurrency-guarded for resource-constrained hardware.
"""
import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.key_manager import key_manager
from backend.app.db.session import get_db
from backend.app.db.models import User, FileRecord, FileChunk, ChunkEmbedding, UsageRecord
from backend.app.api.deps import get_current_user, verify_csrf
from backend.app.schemas.ai import (
    IndexResponse,
    SearchQueryRequest,
    QueryAnswerResponse,
    CitationResponse
)
from backend.app.services.vault import vault_service, unwrap_dek
from backend.app.services.extractor import (
    extractor_service,
    ExtractionError,
    UnsupportedDocumentError
)
from backend.app.services.embedding import embedding_service
from backend.app.services.search import search_service
from backend.app.services.orchestrator import AIOrchestrator

router = APIRouter(prefix="/ai", tags=["Local AI"])

# Concurrency Guard: Restrict simultaneous heavy indexing/inference to 2 concurrent tasks
# to protect memory budget on resource-constrained devices (e.g. Arduino UNO Q 4GB).
AI_CONCURRENCY_SEMAPHORE = asyncio.Semaphore(2)


@router.post("/index/{file_id}", response_model=IndexResponse, status_code=status.HTTP_200_OK)
async def index_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db)
):
    """
    On-Demand Indexing:
    Extracts text, builds FTS5 keyword index, and generates semantic vector embeddings
    ONLY for the specified file owned by the authenticated user.
    Plaintext buffers are held in memory only for chunking and discarded immediately.
    """
    # 1. Verify file ownership and active status
    stmt = select(FileRecord).where(
        FileRecord.id == file_id,
        FileRecord.user_id == current_user.id,
        FileRecord.status == "ACTIVE"
    )
    file_record = (await db.execute(stmt)).scalar_one_or_none()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found in your vault or access denied."
        )

    async with AI_CONCURRENCY_SEMAPHORE:
        # 2. In-memory decryption from vault storage
        try:
            master_kek = key_manager.load_master_key()
            file_dek = unwrap_dek(file_record.wrapped_dek, master_kek)

            plaintext_chunks = []
            for chunk in vault_service.decrypt_vault_stream(file_record.id, file_record.storage_name, file_dek):
                plaintext_chunks.append(chunk)
            raw_bytes = b"".join(plaintext_chunks)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to decrypt file for indexing: {e}"
            )

        # 3. Document text extraction & chunking
        try:
            pages = extractor_service.extract_text_pages(raw_bytes, file_record.original_name)
            chunks = extractor_service.chunk_pages(pages)
        except UnsupportedDocumentError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e)
            )
        except ExtractionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Text extraction failed: {e}"
            )
        finally:
            # Explicitly release raw plaintext reference
            del raw_bytes
            del plaintext_chunks

        # 4. Idempotently clear any existing chunks for this file
        await db.execute(delete(FileChunk).where(FileChunk.file_id == file_id))
        await db.execute(text("DELETE FROM file_chunks_fts WHERE file_id = :file_id"), {"file_id": file_id})

        # 5. Persist extracted chunks and FTS5 index rows
        db_chunks = []
        for c in chunks:
            db_chunk = FileChunk(
                file_id=file_id,
                user_id=current_user.id,
                chunk_index=c.chunk_index,
                page_number=c.page_number,
                content=c.content,
                char_count=c.char_count
            )
            db.add(db_chunk)
            db_chunks.append(db_chunk)

        # Flush to generate chunk UUIDs
        await db.flush()

        # Insert into SQLite FTS5 table
        for c in db_chunks:
            await db.execute(
                text("""
                    INSERT INTO file_chunks_fts (chunk_id, file_id, user_id, content)
                    VALUES (:chunk_id, :file_id, :user_id, :content)
                """),
                {
                    "chunk_id": c.id,
                    "file_id": file_id,
                    "user_id": current_user.id,
                    "content": c.content
                }
            )

        # 6. If user is PREMIUM, generate local semantic vector embeddings
        if current_user.plan_type in {"VAULT_AI", "PREMIUM", "CREATOR"}:
            chunk_texts = [c.content for c in db_chunks]
            embedding_bytes_list = embedding_service.embed_chunks(chunk_texts)

            for c, emb_bytes in zip(db_chunks, embedding_bytes_list):
                emb_record = ChunkEmbedding(
                    chunk_id=c.id,
                    user_id=current_user.id,
                    embedding=emb_bytes,
                    dimensions=embedding_service.dimensions
                )
                db.add(emb_record)

        # 7. Mark file as indexed
        file_record.is_indexed = 1
        await db.commit()

        return IndexResponse(
            file_id=file_id,
            filename=file_record.original_name,
            chunks_created=len(chunks),
            pages_processed=len(pages),
            is_indexed=True,
            message="Document successfully processed and added to local search index."
        )


@router.delete("/index/{file_id}", status_code=status.HTTP_200_OK)
async def unindex_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db)
):
    """
    Removes a document from the AI search index without deleting the encrypted vault file.
    Scrubs all derived chunks, FTS5 rows, and embeddings.
    """
    stmt = select(FileRecord).where(
        FileRecord.id == file_id,
        FileRecord.user_id == current_user.id,
        FileRecord.status == "ACTIVE"
    )
    file_record = (await db.execute(stmt)).scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    await db.execute(delete(FileChunk).where(FileChunk.file_id == file_id))
    await db.execute(text("DELETE FROM file_chunks_fts WHERE file_id = :file_id"), {"file_id": file_id})
    file_record.is_indexed = 0
    await db.commit()

    return {"status": "success", "message": "Document successfully removed from search index."}


@router.post("/query")
async def query_vault_documents(
    payload: SearchQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Streams a grounded answer with citations using the AI Orchestrator.
    """
    orchestrator = AIOrchestrator(db, current_user)

    async def wrapped_generator():
        async with AI_CONCURRENCY_SEMAPHORE:
            async for event in orchestrator.stream_response(
                query=payload.query,
                session_id=payload.session_id, # Support optional session ID
                mode=payload.mode,
                limit=payload.limit
            ):
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(wrapped_generator(), media_type="text/event-stream")


@router.post("/semantic", response_model=QueryAnswerResponse)
async def query_semantic_exclusive(
    payload: SearchQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Dedicated semantic-only vector retrieval endpoint.
    Strictly restricted to PREMIUM subscribers.
    """
    if current_user.plan_type not in {"VAULT_AI", "PREMIUM", "CREATOR"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Semantic vector search requires the Vault + AI plan (Premium capability)."
        )
    payload.mode = "semantic"

    # Collect the stream to maintain compatibility with the non-streaming response model
    tokens = []
    citations = []
    mode = ""

    orchestrator = AIOrchestrator(db, current_user)
    async for event in orchestrator.stream_response(payload.query, mode=payload.mode, limit=payload.limit):
        if "token" in event:
            tokens.append(event["token"])
        if "citations" in event:
            citations = event["citations"]
            mode = event.get("mode", "")

    return QueryAnswerResponse(
        query=payload.query,
        answer="".join(tokens),
        has_sufficient_evidence=True,
        citations=[CitationResponse(**c) for c in citations],
        plan_tier=current_user.plan_type,
        mode_used=mode,
        response_kind="GROUNDED",
    )
