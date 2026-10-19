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
    # Ignore common question words so FTS5 focuses on document keywords.
    stop_words = {
        "who", "what", "where", "when", "why", "how",
        "is", "are", "was", "were", "do", "does", "did",
        "the", "a", "an", "and", "or", "of", "to", "in",
        "on", "for", "by", "with", "wrote",
    }
    tokens = [
        t for t in cleaned.split()
        if len(t) >= 1 and t.casefold() not in stop_words
    ]

    if not tokens:
        return ""

    # Match relevant terms independently. Requiring every natural-language
    # question term made ordinary questions return no evidence.
    fts_tokens = [f'"{token}"*' for token in tokens]
    return " OR ".join(fts_tokens)


def conversational_response(query: str) -> Optional[str]:
    """Return a safe local response for casual chat before document retrieval."""
    normalized = re.sub(r"[^a-z\s]", "", query.casefold()).strip()
    if normalized in {"hi", "hello", "hey", "hiya", "good morning", "good afternoon", "good evening"}:
        return "Hi! I’m CipherQ. I’m ready to help you explore your indexed documents."
    if normalized in {"how are you", "hwo are you", "how r you", "how are u"}:
        return "I’m doing well and ready to help. Ask me about a document in your private vault, and I’ll look for grounded evidence."
    if normalized in {"who are you", "what are you"}:
        return "I’m CipherQ, your private document assistant. I search your authorized indexed files and answer with evidence from your vault."
    if normalized in {"what can you do", "help", "how can you help"}:
        return "I can search indexed vault documents, answer questions from their contents, summarize evidence, and show the sources I used."
    if normalized in {"thanks", "thank you", "thx"}:
        return "You’re welcome. Whenever you’re ready, ask me something about your indexed documents."
    return None


def is_conversational_greeting(query: str) -> bool:
    """Recognize greetings that should not trigger document retrieval."""
    return conversational_response(query) is not None


def is_general_knowledge_request(query: str) -> bool:
    """Detect requests that are not asking about the user's private documents."""
    normalized = re.sub(r"\s+", " ", query.casefold()).strip()
    return (
        normalized.startswith(("tell me about ", "explain ", "write a ", "give me a joke"))
        or normalized in {"what is the weather", "what is the latest news", "tell me a joke"}
        or "latest news" in normalized
        or "weather today" in normalized
    )


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
        min_threshold: float = 0.58
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

    @staticmethod
    def _needs_first_page(query: str) -> bool:
        """Detect explicit title-page, title, or author lookup intent."""
        normalized = re.sub(r"[^a-z0-9\s]", " ", query.casefold())
        normalized = " ".join(normalized.split())
        patterns = (
            r"\bfirst page\b",
            r"\btitle page\b",
            r"\bfull title\b",
            r"\btitle and author\b",
            r"\bauthor name\b",
            r"\bwho wrote\b",
            r"\bwho is the author\b",
            r"\bauthor of\b",
            r"\bwritten by\b",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

    @staticmethod
    def _needs_author_answer(query: str) -> bool:
        normalized = re.sub(r"[^a-z0-9\s]", " ", query.casefold())
        normalized = " ".join(normalized.split())
        return bool(re.search(
            r"\b(author|written by|who wrote|who is the writer)\b",
            normalized,
        ))

    async def search_first_page(
        self,
        db: AsyncSession,
        user_id: str,
        limit: int = 5,
    ) -> List[SearchHit]:
        """Retrieve page-one chunks only from the current user's active files."""
        stmt = (
            select(
                FileChunk.id,
                FileChunk.file_id,
                FileRecord.original_name,
                FileChunk.chunk_index,
                FileChunk.page_number,
                FileChunk.content,
            )
            .join(FileRecord, FileChunk.file_id == FileRecord.id)
            .where(
                FileChunk.user_id == user_id,
                FileRecord.user_id == user_id,
                FileRecord.status == "ACTIVE",
                FileChunk.page_number == 1,
            )
            .order_by(FileRecord.created_at.desc(), FileChunk.chunk_index.asc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        hits = []
        for chunk_id, file_id, filename, chunk_index, page_number, content in result.fetchall():
            snippet = content[:160] + "..." if len(content) > 160 else content
            hits.append(SearchHit(
                chunk_id=chunk_id,
                file_id=file_id,
                filename=filename,
                chunk_index=chunk_index,
                page_number=page_number,
                content=content,
                snippet=snippet,
                score=1.0,
                match_type="FIRST_PAGE_INTENT",
            ))
        return hits

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
        first_page_hits = (
            await self.search_first_page(db, user_id, limit=limit)
            if self._needs_first_page(query)
            else []
        )

        # Title/author questions are answered from title pages only. General
        # FTS/semantic matches contain false positives such as "authorising".
        if first_page_hits and self._needs_author_answer(query):
            return first_page_hits

        if plan_type not in {"VAULT_AI", "PREMIUM", "CREATOR"}:
            normal_hits = await self.search_fts5(
                db, user_id, query, limit=limit
            )
            if not first_page_hits:
                return normal_hits
            seen = {hit.chunk_id for hit in first_page_hits}
            return (
                first_page_hits
                + [hit for hit in normal_hits if hit.chunk_id not in seen]
            )[:limit]

        # Premium tier: Hybrid search
        fts_hits = await self.search_fts5(db, user_id, query, limit=limit)
        semantic_hits = await self.search_semantic(db, user_id, query, limit=limit)

        # Merge results using reciprocal rank fusion. Raw FTS5 and cosine
        # similarity scores are not comparable, so rank each result list first.
        combined = {}
        rank_constant = 60
        keyword_weight = 3.0
        semantic_weight = 1.0

        for rank, hit in enumerate(fts_hits, start=1):
            combined[hit.chunk_id] = (hit, keyword_weight / (rank_constant + rank))

        for rank, hit in enumerate(semantic_hits, start=1):
            contribution = semantic_weight / (rank_constant + rank)
            if hit.chunk_id in combined:
                existing, score = combined[hit.chunk_id]
                combined[hit.chunk_id] = (existing, score + contribution)
                existing.match_type = "HYBRID (FTS5 + SEMANTIC)"
            else:
                combined[hit.chunk_id] = (hit, contribution)

        ranked = sorted(combined.values(), key=lambda item: item[1], reverse=True)
        for hit, fused_score in ranked:
            hit.score = round(fused_score, 4)

        normal_hits = [hit for hit, _ in ranked[:limit]]
        if not first_page_hits:
            return normal_hits
        seen = {hit.chunk_id for hit in first_page_hits}
        return (
            first_page_hits
            + [hit for hit in normal_hits if hit.chunk_id not in seen]
        )[:limit]

    def synthesize_grounded_answer(self, query: str, hits: List[SearchHit]) -> Dict[str, Any]:
        """
        Constructs a grounded, verifiable answer citing source documents and page numbers.
        If no relevant documents are found, returns an explicit insufficient evidence notice.
        Guarantees zero citation fabrication.
        """
        casual_answer = conversational_response(query)
        if casual_answer:
            return {
                "answer": casual_answer,
                "citations": [],
                "has_sufficient_evidence": True,
                "response_kind": "CONVERSATION",
            }

        if is_general_knowledge_request(query):
            return {
                "answer": "That topic is outside your indexed vault. Ask me a question about one of your documents, and I’ll answer from the available evidence.",
                "citations": [],
                "has_sufficient_evidence": True,
                "response_kind": "OUT_OF_SCOPE",
            }

        if not hits:
            return {
                "answer": "I couldn’t find enough evidence in your indexed documents to answer that. Index a file in the Vault and try again.",
                "citations": [],
                "has_sufficient_evidence": False,
                "response_kind": "GROUNDED",
            }

        citations = []
        evidence_points = []
        query_terms = {
            token.casefold()
            for token in re.findall(r"\w+", query)
            if len(token) > 2
        }

        if self._needs_author_answer(query):
            author_matches = []
            for hit in hits:
                match = re.search(
                    r"\b(?:by|written\s+by)\s+"
                    r"([A-Z][A-Za-z.'-]*(?:[ \t]+[A-Z][A-Za-z.'-]*){0,4})",
                    hit.content,
                    flags=re.IGNORECASE,
                )
                if match:
                    author_matches.append(match.group(1).strip(" .,:;"))
            if author_matches:
                author = author_matches[0]
                return {
                    "answer": f"The author is {author}.",
                    "citations": [{
                        "filename": hit.filename,
                        "page_number": hit.page_number,
                        "chunk_index": hit.chunk_index,
                        "snippet": re.sub(r"</?b>", "", hit.snippet),
                        "score": hit.score,
                        "match_type": hit.match_type,
                    } for hit in hits[:1]],
                    "has_sufficient_evidence": True,
                    "response_kind": "GROUNDED",
                }

        for hit in hits:
            # Clean HTML tags in snippet
            clean_snippet = re.sub(r'</?b>', '', hit.snippet)
            sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", hit.content).strip())
            ranked_sentences = sorted(
                sentences,
                key=lambda sentence: len(
                    query_terms.intersection(
                        token.casefold() for token in re.findall(r"\w+", sentence)
                    )
                ),
                reverse=True,
            )
            answer_excerpt = (ranked_sentences[0] if ranked_sentences else clean_snippet).strip()
            if len(answer_excerpt) > 320:
                answer_excerpt = answer_excerpt[:317].rsplit(" ", 1)[0] + "..."
            citations.append({
                "filename": hit.filename,
                "page_number": hit.page_number,
                "chunk_index": hit.chunk_index,
                "snippet": clean_snippet,
                "score": hit.score,
                "match_type": hit.match_type
            })

            evidence_points.append(
                f"- {answer_excerpt}"
            )

        # Construct grounded response
        answer_lines = [
            "I found the following relevant information in your indexed documents:",
            "\n".join(
                f"{index}. {point.removeprefix('- ')}"
                for index, point in enumerate(evidence_points, start=1)
            ),
        ]

        return {
            "answer": "\n".join(answer_lines),
            "citations": citations,
            "has_sufficient_evidence": True,
            "response_kind": "GROUNDED",
        }


search_service = SearchService()
