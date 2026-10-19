"""
CipherQ AI Orchestration Service
Handles LangChain-based RAG pipelines, conversation memory, and intelligent routing.
"""
import logging
import uuid
from typing import AsyncGenerator, List, Tuple, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.db.models import ChatSession, ChatMessage, User
from backend.app.services.search import search_service
from backend.app.services.gemma import stream_grounded_answer
from backend.app.services.search import conversational_response, is_general_knowledge_request

logger = logging.getLogger(__name__)

class AIOrchestrator:
    """
    Orchestrates the flow between user input, document retrieval,
    conversation memory, and LLM generation.
    """

    def __init__(self, db: AsyncSession, user: User):
        self.db = db
        self.user = user

    async def get_or_create_session(self, session_id: Optional[str] = None) -> str:
        """Retrieves an existing session or creates a new one."""
        if session_id:
            stmt = select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == self.user.id
            )
            result = (await self.db.execute(stmt)).scalar_one_or_none()
            if result:
                return result.id

        # Create new session
        new_session = ChatSession(user_id=self.user.id, title="New Conversation")
        self.db.add(new_session)
        await self.db.commit()
        return new_session.id

    async def load_memory(self, session_id: str, limit: int = 10) -> List[Tuple[str, str]]:
        """Loads the last N messages for the given session."""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        messages = result.scalars().all()

        # Reverse to get chronological order
        history = [(m.role, m.content) for m in reversed(messages)]
        return history

    async def save_message(self, session_id: str, role: str, content: str):
        """Persists a message to the database."""
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content
        )
        self.db.add(msg)
        await self.db.commit()

    async def stream_response(
        self,
        query: str,
        session_id: Optional[str] = None,
        mode: str = "auto",
        limit: int = 5
    ) -> AsyncGenerator[dict, None]:
        """
        The main orchestration pipeline:
        1. Session & Memory Management
        2. Intelligent Routing
        3. Advanced Retrieval (Hybrid/Semantic)
        4. Grounded Streaming Generation
        """
        # 1. Session Management
        sid = await self.get_or_create_session(session_id)
        history = await self.load_memory(sid)

        # 2. Routing & Conversational Layer
        # Check if it's a basic greeting first
        casual = conversational_response(query)
        if casual:
            await self.save_message(sid, "user", query)
            await self.save_message(sid, "assistant", casual)
            yield {"answer": casual, "kind": "CONVERSATION", "done": True}
            return

        if is_general_knowledge_request(query):
            answer = "That topic is outside your indexed vault. Ask me a question about one of your documents."
            await self.save_message(sid, "user", query)
            await self.save_message(sid, "assistant", answer)
            yield {"answer": answer, "kind": "OUT_OF_SCOPE", "done": True}
            return

        # 3. Retrieval Phase
        # Note: In a full LangChain impl, we'd use a MultiQueryRetriever here.
        # For now, we utilize the existing search_service which we've verified.
        if mode == "semantic":
            hits = await search_service.search_semantic(self.db, self.user.id, query, limit)
            mode_used = "SEMANTIC_VECTOR"
        elif mode == "keyword":
            hits = await search_service.search_fts5(self.db, self.user.id, query, limit)
            mode_used = "FTS5_KEYWORD"
        else:
            hits = await search_service.hybrid_search(self.db, self.user.id, query, self.user.plan_type, limit)
            mode_used = "HYBRID (FTS5 + SEMANTIC)" if self.user.plan_type != "FREE" else "FTS5_KEYWORD"

        # 4. Synthesis & Metadata
        answer_data = search_service.synthesize_grounded_answer(query, hits)
        citations = [
            {
                "filename": c["filename"],
                "page_number": c["page_number"],
                "chunk_index": c["chunk_index"],
                "snippet": c["snippet"],
                "score": c["score"],
                "match_type": c["match_type"]
            }
            for c in answer_data["citations"]
        ]

        yield {"citations": citations, "mode": mode_used, "kind": "GROUNDED", "done": False}

        # 5. Streaming Generation
        full_response = []
        if self.user.plan_type in {"VAULT_AI", "PREMIUM", "CREATOR"} and hits:
            evidence = [(hit.filename, hit.page_number, hit.content) for hit in hits]
            try:
                async for token in stream_grounded_answer(query, evidence):
                    full_response.append(token)
                    yield {"token": token, "done": False}
            except Exception as e:
                logger.error(f"Streaming failed: {e}")
                # Fallback to deterministic answer
                full_response.append(answer_data["answer"])
                yield {"token": answer_data["answer"], "done": True}
        else:
            # Free tier or no evidence: deterministic synthesis
            full_response.append(answer_data["answer"])
            yield {"token": answer_data["answer"], "done": True}

        # Finalize: Save the full interaction to memory
        final_answer = "".join(full_response)
        await self.save_message(sid, "user", query)
        await self.save_message(sid, "assistant", final_answer)

        yield {"done": True}
