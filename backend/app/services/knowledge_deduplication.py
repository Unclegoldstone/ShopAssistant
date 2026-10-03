from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.knowledge.embedding import Embedder
from app.knowledge.text import build_content_fingerprint, build_vector_text, normalize_questions
from app.knowledge.types import KnowledgeDraft
from app.knowledge.vector_store import VectorSearchHit, VectorStore
from app.models import (
    KnowledgeChunk,
    KnowledgeContentType,
    KnowledgeSourceType,
    KnowledgeStaging,
    KnowledgeStagingStatus,
    KnowledgeVectorStatus,
)
from app.prompts import knowledge_deduplication_prompt
from app.repositories.knowledge import KnowledgeRepository


class DedupDecision(BaseModel):
    decision: Literal["merge", "conflict", "independent"]
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_is_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason 不能为空")
        return value


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    processed: int = 0
    exact_duplicates: int = 0
    merged: int = 0
    conflicts: int = 0
    promoted: int = 0


def choose_semantic_candidate(
    hits: list[VectorSearchHit],
    chunks: dict[int, Any],
    *,
    min_score: float,
) -> Any | None:
    for hit in hits:
        chunk = chunks.get(hit.chunk_id)
        if hit.score < min_score:
            continue
        if (
            chunk is not None
            and chunk.is_active
            and chunk.vector_status is KnowledgeVectorStatus.VECTORIZED
        ):
            return chunk
    return None


def merge_questions(existing: list[str], incoming: list[str]) -> tuple[str, ...]:
    return normalize_questions([*existing, *incoming])


class KnowledgeDeduplicationService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        vector_store: VectorStore,
        model: Any,
        candidate_score: float,
        candidate_top_k: int = 5,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._vector_store = vector_store
        self._structured_model = model.with_structured_output(
            DedupDecision,
            method="json_schema",
            strict=True,
        )
        self._candidate_score = candidate_score
        self._candidate_top_k = candidate_top_k

    async def run_once(self, *, limit: int = 100) -> DeduplicationResult:
        await self._vector_store.ensure_collection()
        staging_items = await self._load_staging(limit)
        totals = {
            "processed": 0,
            "exact_duplicates": 0,
            "merged": 0,
            "conflicts": 0,
            "promoted": 0,
        }
        promoted_in_run: list[tuple[KnowledgeChunk, list[float]]] = []

        for staging in staging_items:
            totals["processed"] += 1
            draft = _staging_to_draft(staging)
            exact = await self._find_exact(draft)
            if exact is not None:
                await self._mark_exact(staging.id, exact.id)
                totals["exact_duplicates"] += 1
                continue

            vector = (await self._embedder.embed([build_vector_text(draft)]))[0]
            candidate = await self._find_semantic_candidate(vector)
            memory_candidate = _best_memory_candidate(
                vector,
                promoted_in_run,
                min_score=self._candidate_score,
            )
            if candidate is None:
                candidate = memory_candidate

            if candidate is None:
                promoted = await self._promote(staging.id, draft, "无高相似候选")
                promoted_in_run.append((promoted, vector))
                totals["promoted"] += 1
                continue

            decision = await self._decide(candidate, draft)
            if decision.decision == "merge":
                await self._merge(staging.id, candidate.id, draft, decision.reason)
                totals["merged"] += 1
            else:
                promoted = await self._promote(
                    staging.id,
                    draft,
                    decision.reason,
                    conflict=decision.decision == "conflict",
                )
                promoted_in_run.append((promoted, vector))
                totals["promoted"] += 1
                if decision.decision == "conflict":
                    totals["conflicts"] += 1
        return DeduplicationResult(**totals)

    async def _load_staging(self, limit: int) -> list[KnowledgeStaging]:
        async with self._session_factory() as session:
            statement = (
                select(KnowledgeStaging)
                .where(KnowledgeStaging.status == KnowledgeStagingStatus.EXTRACTED)
                .order_by(KnowledgeStaging.id)
                .limit(limit)
            )
            return list(await session.scalars(statement))

    async def _find_exact(self, draft: KnowledgeDraft) -> KnowledgeChunk | None:
        fingerprint = build_content_fingerprint(draft)
        async with self._session_factory() as session:
            statement = (
                select(KnowledgeChunk)
                .where(
                    KnowledgeChunk.content_fingerprint == fingerprint,
                    KnowledgeChunk.is_active.is_(True),
                )
                .order_by(KnowledgeChunk.id)
                .limit(1)
            )
            return await session.scalar(statement)

    async def _find_semantic_candidate(self, vector: list[float]) -> KnowledgeChunk | None:
        hits = await self._vector_store.search(vector, top_k=self._candidate_top_k)
        async with self._session_factory() as session:
            chunks = await KnowledgeRepository(session).get_by_ids_in_order(
                [hit.chunk_id for hit in hits]
            )
        return choose_semantic_candidate(
            hits,
            {chunk.id: chunk for chunk in chunks},
            min_score=self._candidate_score,
        )

    async def _decide(
        self,
        existing: KnowledgeChunk,
        incoming: KnowledgeDraft,
    ) -> DedupDecision:
        messages = knowledge_deduplication_prompt.format_messages(
            existing=_knowledge_json(existing.category, existing.questions, existing.answer),
            incoming=_knowledge_json(incoming.category, incoming.questions, incoming.answer),
        )
        result = await self._structured_model.ainvoke(messages)
        return result if isinstance(result, DedupDecision) else DedupDecision.model_validate(result)

    async def _mark_exact(self, staging_id: int, target_id: int) -> None:
        async with self._session_factory.begin() as session:
            staging = await session.get(KnowledgeStaging, staging_id)
            if staging is None:
                raise LookupError("暂存知识不存在")
            staging.status = KnowledgeStagingStatus.EXACT_DUPLICATE
            staging.duplicate_target_chunk_id = target_id
            staging.decision_reason = "稳定内容指纹完全相同"

    async def _merge(
        self,
        staging_id: int,
        target_id: int,
        incoming: KnowledgeDraft,
        reason: str,
    ) -> None:
        async with self._session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            existing = await repository.get(target_id)
            staging = await session.get(KnowledgeStaging, staging_id)
            if existing is None or staging is None:
                raise LookupError("去重目标不存在")
            merged = KnowledgeDraft(
                source_type=existing.source_type,
                source_key=existing.source_key,
                source_revision=existing.source_revision,
                category=existing.category,
                questions=merge_questions(existing.questions, list(incoming.questions)),
                answer=existing.answer,
                section_path=tuple(existing.section_path),
                content_type=existing.content_type,
                is_critical=existing.is_critical or incoming.is_critical,
            )
            result = await repository.upsert_chunk(merged)
            staging.status = KnowledgeStagingStatus.MERGED
            staging.duplicate_target_chunk_id = result.chunk.id
            staging.promoted_chunk_id = result.chunk.id
            staging.decision_reason = reason

    async def _promote(
        self,
        staging_id: int,
        draft: KnowledgeDraft,
        reason: str,
        *,
        conflict: bool = False,
    ) -> KnowledgeChunk:
        async with self._session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            result = await repository.upsert_chunk(draft)
            staging = await session.get(KnowledgeStaging, staging_id)
            if staging is None:
                raise LookupError("暂存知识不存在")
            staging.status = (
                KnowledgeStagingStatus.CONFLICT
                if conflict
                else KnowledgeStagingStatus.PROMOTED
            )
            staging.promoted_chunk_id = result.chunk.id
            staging.decision_reason = reason
            return result.chunk


def _staging_to_draft(staging: KnowledgeStaging) -> KnowledgeDraft:
    return KnowledgeDraft(
        source_type=KnowledgeSourceType.CONVERSATION,
        source_key=(
            f"conversation:{staging.conversation_id}:"
            f"{staging.first_message_id}-{staging.last_message_id}:{staging.item_index}"
        ),
        source_revision=staging.content_fingerprint,
        category=staging.category,
        questions=tuple(staging.questions),
        answer=staging.answer,
        section_path=("历史客服对话", staging.category),
        content_type=KnowledgeContentType.CONVERSATION_QA,
        is_critical=staging.is_critical,
    )


def _knowledge_json(category: str, questions: list[str] | tuple[str, ...], answer: str) -> str:
    return json.dumps(
        {"category": category, "questions": list(questions), "answer": answer},
        ensure_ascii=False,
    )


def _best_memory_candidate(
    vector: list[float],
    candidates: list[tuple[KnowledgeChunk, list[float]]],
    *,
    min_score: float,
) -> KnowledgeChunk | None:
    norm = math.sqrt(sum(value * value for value in vector))
    best: tuple[float, KnowledgeChunk] | None = None
    for chunk, candidate_vector in candidates:
        candidate_norm = math.sqrt(sum(value * value for value in candidate_vector))
        denominator = norm * candidate_norm
        score = (
            sum(left * right for left, right in zip(vector, candidate_vector, strict=True))
            / denominator
            if denominator
            else -1.0
        )
        if score >= min_score and (best is None or score > best[0]):
            best = (score, chunk)
    return best[1] if best else None
