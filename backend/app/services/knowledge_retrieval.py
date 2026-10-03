from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.knowledge.embedding import Embedder
from app.knowledge.vector_store import VectorStore
from app.models import KnowledgeChunk, KnowledgeVectorStatus
from app.repositories.knowledge import KnowledgeRepository


@dataclass(frozen=True, slots=True)
class KnowledgeMatch:
    chunk_id: int
    question: str
    answer: str
    category: str
    score: float


ChunkLoader = Callable[[list[int]], Awaitable[list[KnowledgeChunk]]]


class KnowledgeRetrievalService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None,
        embedder: Embedder,
        vector_store: VectorStore,
        top_k: int,
        min_score: float,
        chunk_loader: ChunkLoader | None = None,
    ) -> None:
        if session_factory is None and chunk_loader is None:
            raise ValueError("必须提供数据库 session_factory 或 chunk_loader")
        self._session_factory = session_factory
        self._embedder = embedder
        self._vector_store = vector_store
        self._top_k = top_k
        self._min_score = min_score
        self._chunk_loader = chunk_loader

    async def search(self, query: str, *, top_k: int | None = None) -> list[KnowledgeMatch]:
        query = query.strip()
        if not query:
            return []
        requested_top_k = self._top_k if top_k is None else top_k
        if requested_top_k <= 0:
            raise ValueError("top_k 必须为正数")
        vector = (await self._embedder.embed([query]))[0]
        hits = await self._vector_store.search(vector, top_k=requested_top_k)
        eligible_hits = [hit for hit in hits if hit.score >= self._min_score]
        chunks = await self._load_chunks([hit.chunk_id for hit in eligible_hits])
        by_id = {chunk.id: chunk for chunk in chunks}
        matches: list[KnowledgeMatch] = []
        for hit in eligible_hits:
            chunk = by_id.get(hit.chunk_id)
            if (
                chunk is None
                or not chunk.is_active
                or chunk.vector_status is not KnowledgeVectorStatus.VECTORIZED
            ):
                continue
            matches.append(
                KnowledgeMatch(
                    chunk_id=chunk.id,
                    question=" / ".join(sorted(chunk.questions)),
                    answer=chunk.answer,
                    category=chunk.category,
                    score=hit.score,
                )
            )
        return matches

    async def _load_chunks(self, chunk_ids: list[int]) -> list[KnowledgeChunk]:
        if self._chunk_loader is not None:
            return await self._chunk_loader(chunk_ids)
        if self._session_factory is None:
            return []
        async with self._session_factory() as session:
            return await KnowledgeRepository(session).get_by_ids_in_order(chunk_ids)
