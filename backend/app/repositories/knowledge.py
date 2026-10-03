from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.text import build_content_fingerprint
from app.knowledge.types import KnowledgeDraft
from app.models import KnowledgeChunk, KnowledgeVectorStatus

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret)\s*[=:]\s*[^\s,;]+"
)


@dataclass(frozen=True, slots=True)
class KnowledgeUpsertResult:
    chunk: KnowledgeChunk
    created: bool
    changed: bool


def sanitize_error_summary(error: BaseException | str, *, max_length: int = 1000) -> str:
    value = " ".join(str(error).split())
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", value)
    return value[:max_length]


class KnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, chunk_id: int) -> KnowledgeChunk | None:
        return await self._session.get(KnowledgeChunk, chunk_id)

    async def get_by_source_key(self, source_key: str) -> KnowledgeChunk | None:
        statement = select(KnowledgeChunk).where(KnowledgeChunk.source_key == source_key)
        return await self._session.scalar(statement)

    async def upsert_chunk(self, draft: KnowledgeDraft) -> KnowledgeUpsertResult:
        statement = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.source_key == draft.source_key)
            .with_for_update()
        )
        chunk = await self._session.scalar(statement)
        fingerprint = build_content_fingerprint(draft)

        if chunk is None:
            chunk = KnowledgeChunk(
                source_type=draft.source_type,
                source_key=draft.source_key,
                source_revision=draft.source_revision,
                category=draft.category,
                questions=list(draft.questions),
                answer=draft.answer,
                section_path=list(draft.section_path),
                content_type=draft.content_type,
                is_critical=draft.is_critical,
                content_fingerprint=fingerprint,
            )
            self._session.add(chunk)
            await self._session.flush()
            return KnowledgeUpsertResult(chunk=chunk, created=True, changed=True)

        fields_changed = any(
            (
                chunk.source_type != draft.source_type,
                chunk.source_revision != draft.source_revision,
                chunk.category != draft.category,
                chunk.questions != list(draft.questions),
                chunk.answer != draft.answer,
                chunk.section_path != list(draft.section_path),
                chunk.content_type != draft.content_type,
                chunk.is_critical != draft.is_critical,
                chunk.content_fingerprint != fingerprint,
                not chunk.is_active,
                chunk.vector_status is KnowledgeVectorStatus.PENDING_DELETE,
            )
        )
        if not fields_changed:
            return KnowledgeUpsertResult(chunk=chunk, created=False, changed=False)

        requires_revectorization = (
            chunk.content_fingerprint != fingerprint
            or not chunk.is_active
            or chunk.vector_status is KnowledgeVectorStatus.PENDING_DELETE
        )
        chunk.source_type = draft.source_type
        chunk.source_revision = draft.source_revision
        chunk.category = draft.category
        chunk.questions = list(draft.questions)
        chunk.answer = draft.answer
        chunk.section_path = list(draft.section_path)
        chunk.content_type = draft.content_type
        chunk.is_critical = draft.is_critical
        chunk.content_fingerprint = fingerprint
        chunk.is_active = True

        if requires_revectorization:
            chunk.vector_status = KnowledgeVectorStatus.PENDING
            chunk.embedding_model = None
            chunk.embedding_version = None
            chunk.vector_attempts = 0
            chunk.vector_error = None
            chunk.vectorizing_started_at = None

        await self._session.flush()
        return KnowledgeUpsertResult(chunk=chunk, created=False, changed=True)

    async def get_by_ids_in_order(self, chunk_ids: list[int]) -> list[KnowledgeChunk]:
        if not chunk_ids:
            return []
        statement = select(KnowledgeChunk).where(KnowledgeChunk.id.in_(set(chunk_ids)))
        chunks = list(await self._session.scalars(statement))
        by_id = {chunk.id: chunk for chunk in chunks}
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]

    async def list_by_source_type(
        self,
        source_type: object,
    ) -> list[KnowledgeChunk]:
        statement = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.source_type == source_type)
            .order_by(KnowledgeChunk.id)
        )
        return list(await self._session.scalars(statement))

    async def set_neighbors(
        self,
        chunk_id: int,
        *,
        previous_chunk_id: int | None,
        next_chunk_id: int | None,
    ) -> None:
        chunk = await self._require(chunk_id)
        chunk.previous_chunk_id = previous_chunk_id
        chunk.next_chunk_id = next_chunk_id
        await self._session.flush()

    async def deactivate_missing_sources(
        self,
        source_type: object,
        active_source_keys: set[str],
        *,
        source_key_prefix: str,
    ) -> int:
        chunks = await self.list_by_source_type(source_type)
        changed = 0
        for chunk in chunks:
            if (
                chunk.source_key.startswith(source_key_prefix)
                and chunk.source_key not in active_source_keys
                and chunk.is_active
            ):
                await self.mark_pending_delete(chunk.id)
                changed += 1
        return changed

    async def claim_pending_deletes(
        self,
        *,
        limit: int,
        chunk_ids: list[int] | None = None,
    ) -> list[KnowledgeChunk]:
        criteria = [
            KnowledgeChunk.vector_status == KnowledgeVectorStatus.PENDING_DELETE,
            KnowledgeChunk.vector_id.is_not(None),
        ]
        if chunk_ids is not None:
            if not chunk_ids:
                return []
            criteria.append(KnowledgeChunk.id.in_(set(chunk_ids)))
        statement = (
            select(KnowledgeChunk)
            .where(*criteria)
            .order_by(KnowledgeChunk.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(await self._session.scalars(statement))

    async def mark_vector_deleted(self, chunk_id: int) -> KnowledgeChunk:
        chunk = await self._require(chunk_id)
        chunk.vector_id = None
        chunk.embedding_model = None
        chunk.embedding_version = None
        chunk.vector_error = None
        chunk.vectorizing_started_at = None
        await self._session.flush()
        return chunk

    async def claim_for_vectorization(
        self,
        *,
        limit: int,
        lease_timeout: timedelta,
        max_attempts: int,
        now: datetime | None = None,
        chunk_ids: list[int] | None = None,
    ) -> list[KnowledgeChunk]:
        claimed_at = now or datetime.now(UTC).replace(tzinfo=None)
        lease_expired_before = claimed_at - lease_timeout
        retryable = and_(
            KnowledgeChunk.vector_attempts < max_attempts,
            or_(
                KnowledgeChunk.vector_status == KnowledgeVectorStatus.PENDING,
                KnowledgeChunk.vector_status == KnowledgeVectorStatus.FAILED,
                and_(
                    KnowledgeChunk.vector_status == KnowledgeVectorStatus.VECTORIZING,
                    KnowledgeChunk.vectorizing_started_at < lease_expired_before,
                ),
            ),
        )
        criteria = [KnowledgeChunk.is_active.is_(True), retryable]
        if chunk_ids is not None:
            if not chunk_ids:
                return []
            criteria.append(KnowledgeChunk.id.in_(set(chunk_ids)))
        statement = (
            select(KnowledgeChunk)
            .where(*criteria)
            .order_by(KnowledgeChunk.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        chunks = list(await self._session.scalars(statement))
        for chunk in chunks:
            chunk.vector_status = KnowledgeVectorStatus.VECTORIZING
            chunk.vectorizing_started_at = claimed_at
            chunk.vector_attempts += 1
            chunk.vector_error = None
        await self._session.flush()
        return chunks

    async def mark_vectorized(
        self,
        chunk_id: int,
        *,
        vector_id: str,
        embedding_model: str,
        embedding_version: str,
    ) -> KnowledgeChunk:
        chunk = await self._require(chunk_id)
        chunk.vector_status = KnowledgeVectorStatus.VECTORIZED
        chunk.vector_id = vector_id
        chunk.embedding_model = embedding_model
        chunk.embedding_version = embedding_version
        chunk.vector_error = None
        chunk.vectorizing_started_at = None
        await self._session.flush()
        return chunk

    async def mark_failed(self, chunk_id: int, error: BaseException | str) -> KnowledgeChunk:
        chunk = await self._require(chunk_id)
        chunk.vector_status = KnowledgeVectorStatus.FAILED
        chunk.vector_error = sanitize_error_summary(error)
        chunk.vectorizing_started_at = None
        await self._session.flush()
        return chunk

    async def mark_pending_delete(self, chunk_id: int) -> KnowledgeChunk:
        chunk = await self._require(chunk_id)
        chunk.is_active = False
        chunk.vector_status = KnowledgeVectorStatus.PENDING_DELETE
        chunk.vector_error = None
        chunk.vectorizing_started_at = None
        await self._session.flush()
        return chunk

    async def _require(self, chunk_id: int) -> KnowledgeChunk:
        chunk = await self.get(chunk_id)
        if chunk is None:
            raise LookupError("知识块不存在")
        return chunk
