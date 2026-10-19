"""
CipherQ Validation Schemas for On-Demand Local AI Search and Grounded Retrieval
"""
from typing import List
from pydantic import BaseModel, Field


class IndexResponse(BaseModel):
    file_id: str
    filename: str
    chunks_created: int
    pages_processed: int
    is_indexed: bool
    message: str


class SearchQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Natural language search query")
    mode: str = Field(default="auto", description="Search mode: auto, keyword, semantic")
    limit: int = Field(default=5, ge=1, le=20)


class CitationResponse(BaseModel):
    filename: str
    page_number: int
    chunk_index: int
    snippet: str
    score: float
    match_type: str


class QueryAnswerResponse(BaseModel):
    query: str
    answer: str
    has_sufficient_evidence: bool
    citations: List[CitationResponse]
    plan_tier: str
    mode_used: str
    response_kind: str = "GROUNDED"
