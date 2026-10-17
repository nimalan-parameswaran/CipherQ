"""
CipherQ Database Models (SQLAlchemy Declarative Models)
Defines normalized schemas with cascade deletions, foreign keys, and indexes.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    LargeBinary,
    Index
)
from sqlalchemy.orm import relationship

from backend.app.db.session import Base


def utc_now() -> datetime:
    """Helper to return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class User(Base):
    """User account model supporting Free and Premium subscription tiers."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    plan_type = Column(String(20), nullable=False, default="FREE")  # "FREE" or "PREMIUM"
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    # Relationships
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    files = relationship("FileRecord", back_populates="user", cascade="all, delete-orphan")
    usage = relationship("UsageRecord", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Session(Base):
    """Authenticated user session. Stored hashed with SHA-256 for token theft defense."""
    __tablename__ = "sessions"

    token_hash = Column(String(64), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    csrf_token = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    user = relationship("User", back_populates="sessions")


class FileRecord(Base):
    """Encrypted file metadata and key references in the vault."""
    __tablename__ = "files"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    original_name = Column(String(255), nullable=False)
    storage_name = Column(String(255), unique=True, nullable=False, index=True)
    file_size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=False, default="application/octet-stream")
    sha256_hash = Column(String(64), nullable=False)
    wrapped_dek = Column(LargeBinary, nullable=False)
    nonce_or_header = Column(LargeBinary, nullable=False)
    status = Column(String(20), nullable=False, default="ACTIVE", index=True)  # "ACTIVE", "PENDING_DELETION"
    is_indexed = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    user = relationship("User", back_populates="files")
    chunks = relationship("FileChunk", back_populates="file", cascade="all, delete-orphan")


class FileChunk(Base):
    """
    Extracted text passage from an indexed vault file.
    Retains page and sequence metadata for grounded citations.
    """
    __tablename__ = "file_chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    file_id = Column(String(36), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=False, default=1)
    content = Column(String, nullable=False)
    char_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    file = relationship("FileRecord", back_populates="chunks")
    embedding = relationship("ChunkEmbedding", back_populates="chunk", uselist=False, cascade="all, delete-orphan")


class ChunkEmbedding(Base):
    """Vector embedding bytes for semantic search."""
    __tablename__ = "chunk_embeddings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chunk_id = Column(String(36), ForeignKey("file_chunks.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    embedding = Column(LargeBinary, nullable=False)  # Packed float32 bytes
    dimensions = Column(Integer, nullable=False, default=384)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    chunk = relationship("FileChunk", back_populates="embedding")


class CleanupQueue(Base):
    """
    Durable, retryable cleanup queue.
    Guarantees asynchronous/retryable physical deletion of vault files and AI chunks.
    """
    __tablename__ = "cleanup_queue"

    task_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    file_id = Column(String(36), nullable=False, index=True)
    storage_path = Column(String(512), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING", index=True)  # PENDING, IN_PROGRESS, FAILED, COMPLETED
    retry_count = Column(Integer, nullable=False, default=0)
    last_error = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class UsageRecord(Base):
    """User storage and daily AI quota tracking."""
    __tablename__ = "usage_records"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    storage_bytes_used = Column(Integer, nullable=False, default=0)
    ai_queries_today = Column(Integer, nullable=False, default=0)
    last_query_date = Column(String(10), nullable=True)

    user = relationship("User", back_populates="usage")


# Composite indexes for fast queries
Index("ix_files_user_status", FileRecord.user_id, FileRecord.status)
Index("ix_chunks_user_file", FileChunk.user_id, FileChunk.file_id)
Index("ix_embeddings_user", ChunkEmbedding.user_id)
Index("ix_cleanup_status_retries", CleanupQueue.status, CleanupQueue.retry_count)
