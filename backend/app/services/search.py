"""
CipherQ Document Search & Grounded Retrieval Service
Implements SQLite FTS5 Keyword Search and Local Semantic Vector Search.
Enforces strict multi-tenant user isolation (User A cannot search User B's documents).
Provides grounded answer generation with verifiable document and page citations.
"""
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.future import select

from backend.app.db.models import FileRecord, FileChunk, ChunkEmbedding
from backend.app.services.embedding import embedding_service


@dataclass
class SearchHit:
    chunk_id: str
    file_id: str
    filename: str
    chunk_index: int
    page_number: int
    content: str
    snippet: str
    score: float
    match_type: str


@dataclass
class Citation:
    filename: str
    page_number: int
    chunk_index: int
    snippet: str


def sanitize_fts5_query(raw_query: str) -> str:
    """
    Cleans user input to prevent FTS5 syntax errors.
    Removes syntax control operators and generates safe prefix-match tokens.
    """
    if not raw_query:
        return ""

    # Keep only alphanumeric and space characters
    cleaned = re.sub(r'[^\w\s]', ' ', raw_query).strip()
    tokens = [t for t in cleaned.split() if len(t) >= 1]

    if not tokens:
        return ""

    # Wrap tokens in quotes and append wildcard for prefix matching: "token"*
    fts_tokens = [f'"{token}"*' for token in tokens]
    return " ".join(fts_tokens)


class SearchService:
    """Unified search engine combining FTS5 keyword indexing and semantic vectors."""

    async def search_fts5(
        self,
        db: AsyncSession,
        user_id: str,
        query: str,
        limit: int = 5
    ) -> List[SearchHit]:
        """
        Fast keyword search via SQLite FTS5 with BM25 ranking.
        Strictly isolated by user_id.
        """
        sanitized = sanitize_fts5_query(query)
        if not sanitized:
            return []

        sql = text("""
            SELECT
                c.id AS chunk_id,
                c.file_id,
                f.original_name AS filename,
                c.chunk_index,
                c.page_number,
                c.content,
                snippet(file_chunks_fts, 3, '<b>', '</b>', '...', 15) AS snippet_text,
                bm25(file_chunks_fts) AS bm25_score
            FROM file_chunks_fts
            JOIN file_chunks c ON file_chunks_fts.chunk_id = c.id
            JOIN files f ON c.file_id = f.id
            WHERE file_chunks_fts.user_id = :user_id
              AND f.status = 'ACTIVE'
              AND file_chunks_fts MATCH :match_query
            ORDER BY bm25_score ASC
            LIMIT :limit
        """)

        try:
            res = await db.execute(sql, {"user_id": user_id, "match_query": sanitized, "limit": limit})
            rows = res.fetchall()
        except Exception:
            return []

        hits = []
        for r in rows:
            # BM25 is negative-lower-is-better; convert to positive normalized score
            norm_score = max(0.1, 1.0 / (1.0 + abs(float(r.bm25_score))))
            hits.append(SearchHit(
                chunk_id=r.chunk_id,
                file_id=r.file_id,
                filename=r.filename,
                chunk_index=r.chunk_index,
                page_number=r.page_number,
                content=r.content,
                snippet=r.snippet_text or (r.content[:160] + "..."),
                score=round(norm_score, 4),
                match_type="FTS5_KEYWORD"
            ))

        return hits

    async def search_semantic(
        self,
        db: AsyncSession,
        user_id: str,
        query: str,
        limit: int = 5,
        min_threshold: float = 0.50
    ) -> List[SearchHit]:
        """
        Semantic vector search via cosine similarity across local 384-dimensional embeddings.
        Strictly isolated by user_id.
        """
        if not query or not query.strip():
            return []

        # 1. Generate query vector
        query_vec = embedding_service.embed_text(query)

        # 2. Fetch all chunk embeddings owned by the user for active files
        stmt = (
            select(
                ChunkEmbedding.chunk_id,
                ChunkEmbedding.embedding,
                FileChunk.file_id,
                FileChunk.chunk_index,
                FileChunk.page_number,
                FileChunk.content,
                FileRecord.original_name
            )
            .join(FileChunk, ChunkEmbedding.chunk_id == FileChunk.id)
            .join(FileRecord, FileChunk.file_id == FileRecord.id)
            .where(
                ChunkEmbedding.user_id == user_id,
                FileRecord.status == "ACTIVE"
            )
        )
        res = await db.execute(stmt)
        rows = res.fetchall()

        if not rows:
            return []

        scored_hits = []
        for chunk_id, emb_bytes, file_id, idx, page, content, fname in rows:
            chunk_vec = np.frombuffer(emb_bytes, dtype=np.float32)
            similarity = embedding_service.compute_similarity(query_vec, chunk_vec)
            
            if similarity >= min_threshold:
                # Find best matching excerpt for snippet
                snippet = content[:160] + "..." if len(content) > 160 else content
                scored_hits.append(SearchHit(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    filename=fname,
                    chunk_index=idx,
                    page_number=page,
                    content=content,
                    snippet=snippet,
                    score=round(similarity, 4),
                    match_type="SEMANTIC_VECTOR"
                ))

        # Sort descending by similarity
        scored_hits.sort(key=lambda x: x.score, reverse=True)
        return scored_hits[:limit]

    async def hybrid_search(
        self,
        db: AsyncSession,
        user_id: str,
        query: str,
        plan_type: str = "FREE",
        limit: int = 5
    ) -> List[SearchHit]:
        """
        Combined retrieval:
        - FREE Plan: SQLite FTS5 Keyword Search.
        - PREMIUM Plan: Combined Keyword + Semantic Vector Search with rank blending.
        """
        if plan_type != "PREMIUM":
            # Free tier: Keyword search only
            return await self.search_fts5(db, user_id, query, limit=limit)

        # Premium tier: Hybrid search
        fts_hits = await self.search_fts5(db, user_id, query, limit=limit)
        semantic_hits = await self.search_semantic(db, user_id, query, limit=limit)

        # Merge and de-duplicate by chunk_id
        combined = {}
        for h in fts_hits:
            combined[h.chunk_id] = h

        for sh in semantic_hits:
            if sh.chunk_id in combined:
                # Blend scores if matched in both
                existing = combined[sh.chunk_id]
                existing.score = round(max(existing.score, sh.score) * 1.15, 4)
                existing.match_type = "HYBRID (FTS5 + SEMANTIC)"
            else:
                combined[sh.chunk_id] = sh

        ranked = sorted(combined.values(), key=lambda x: x.score, reverse=True)
        return ranked[:limit]

    def synthesize_grounded_answer(self, query: str, hits: List[SearchHit]) -> Dict[str, Any]:
        """
        Constructs a grounded, verifiable answer citing source documents and page numbers.
        If no relevant documents are found, returns an explicit insufficient evidence notice.
        Guarantees zero citation fabrication.
        """
        if not hits:
            return {
                "answer": "The indexed documents in your vault do not contain sufficient evidence to answer this query.",
                "citations": [],
                "has_sufficient_evidence": False
            }

        citations = []
        evidence_points = []

        for hit in hits:
            # Clean HTML tags in snippet
            clean_snippet = re.sub(r'</?b>', '', hit.snippet)
            citations.append({
                "filename": hit.filename,
                "page_number": hit.page_number,
                "chunk_index": hit.chunk_index,
                "snippet": clean_snippet,
                "score": hit.score,
                "match_type": hit.match_type
            })

            evidence_points.append(
                f"- **{hit.filename}** (Page {hit.page_number}): \"{clean_snippet}\""
            )

        # Construct grounded response
        answer_lines = [
            f"Based on evidence retrieved directly from your private vault documents for query *\"{query}\"*:\n",
            "\n".join(evidence_points),
            f"\n\n*All references cited above originate from authenticated local vault documents.*"
        ]

        return {
            "answer": "\n".join(answer_lines),
            "citations": citations,
            "has_sufficient_evidence": True
        }


search_service = SearchService()
