"""
CipherQ Pydantic v2 Schemas for File Management
Ensures strict validation and zero exposure of wrapped DEKs or nonces.
"""
from datetime import datetime
from typing import List
from pydantic import BaseModel, ConfigDict


class FileResponse(BaseModel):
    id: str
    original_name: str
    file_size_bytes: int
    mime_type: str
    sha256_hash: str
    status: str
    is_indexed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FileListResponse(BaseModel):
    files: List[FileResponse]
    total_count: int
    storage_bytes_used: int
    storage_quota_bytes: int


class FileDeleteResponse(BaseModel):
    message: str
    file_id: str
    task_id: str
    status: str
