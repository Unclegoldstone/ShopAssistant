from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.knowledge.embedding import Embedder
from app.knowledge.text import build_vector_text
from app.knowledge.types import KnowledgeDraft
from app.knowledge.vector_store import VectorRecord, VectorStore
from app.models import KnowledgeChunk
from app.repositories.knowledge import KnowledgeRepository


@dataclass(frozen=True, slots=True)
class VectorizationResult:
    claimed: int = 0
    vectorized: int = 0
    failed: int = 0
    deleted: int = 0


FailureHook = Callable[[str, int, int], None]


class KnowledgeVectorizationWorker:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        vector_store: VectorStore,
        embedding_model: str,
        embedding_version: str,
        batch_size: int,
        lease_timeout: timedelta,
        max_attempts: int,
        failure_hook: FailureHook | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._vector_store = vector_store
        self._embedding_model = embedding_model
        self._embedding_version = embedding_version
        self._batch_size = batch_size
        self._lease_timeout = lease_timeout
        self._max_attempts = max_attempts
        self._failure_hook = failure_hook

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        chunk_ids: list[int] | None = None,
    ) -> VectorizationResult:
        await self._vector_store.ensure_collection()
        deleted = await self._delete_pending_vectors(chunk_ids=chunk_ids)
        async with self._session_factory.begin() as session:
            claimed = await KnowledgeRepository(session).claim_for_vectorization(
                limit=self._batch_size,
                lease_timeout=self._lease_timeout,
                max_attempts=self._max_attempts,
                now=now,
                chunk_ids=chunk_ids,
            )

        vectorized = 0
        failed = 0
        for index, chunk in enumerate(claimed):
            try:
                vector = (await self._embedder.embed([_vector_text(chunk)]))[0]
                self._inject("before_upsert", chunk.id, index)
                await self._vector_store.upsert(
                    [VectorRecord(chunk.id, vector, self._embedding_version)]
                )
                self._inject("after_upsert", chunk.id, index)
                async with self._session_factory.begin() as session:
                    await KnowledgeRepository(session).mark_vectorized(
                        chunk.id,
                        vector_id=str(chunk.id),
                        embedding_model=self._embedding_model,
                        embedding_version=self._embedding_version,
                    )
                vectorized += 1
            except Exception as exc:
                async with self._session_factory.begin() as session:
                    await KnowledgeRepository(session).mark_failed(chunk.id, exc)
                failed += 1
        return VectorizationResult(
            claimed=len(claimed),
            vectorized=vectorized,
            failed=failed,
            deleted=deleted,
        )

    async def run_until_idle(self) -> VectorizationResult:
        total = VectorizationResult()
        while True:
            current = await self.run_once()
            total = VectorizationResult(
                claimed=total.claimed + current.claimed,
                vectorized=total.vectorized + current.vectorized,
                failed=total.failed + current.failed,
                deleted=total.deleted + current.deleted,
            )
            if current.claimed == 0 and current.deleted >= self._batch_size:
                continue
            if current.claimed == 0 or current.vectorized == 0:
                return total

    def _inject(self, stage: str, chunk_id: int, index: int) -> None:
        if self._failure_hook is not None:
            self._failure_hook(stage, chunk_id, index)

    async def _delete_pending_vectors(self, *, chunk_ids: list[int] | None) -> int:
        async with self._session_factory.begin() as session:
            chunks = await KnowledgeRepository(session).claim_pending_deletes(
                limit=self._batch_size,
                chunk_ids=chunk_ids,
            )
        deleted = 0
        for index, chunk in enumerate(chunks):
            self._inject("before_delete", chunk.id, index)
            await self._vector_store.delete([chunk.id])
            self._inject("after_delete", chunk.id, index)
            async with self._session_factory.begin() as session:
                await KnowledgeRepository(session).mark_vector_deleted(chunk.id)
            deleted += 1
        return deleted


def _vector_text(chunk: KnowledgeChunk) -> str:
    draft = KnowledgeDraft(
        source_type=chunk.source_type,
        source_key=chunk.source_key,
        source_revision=chunk.source_revision,
        category=chunk.category,
        questions=tuple(chunk.questions),
        answer=chunk.answer,
        section_path=tuple(chunk.section_path),
        content_type=chunk.content_type,
        is_critical=chunk.is_critical,
    )
    return build_vector_text(draft)
