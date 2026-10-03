from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.config import Settings
from app.db.session import create_database_runtime
from app.knowledge.text import build_content_fingerprint
from app.knowledge.types import KnowledgeDraft
from app.knowledge.vector_store import VectorSearchHit
from app.models import (
    Conversation,
    ConversationStatus,
    KnowledgeChunk,
    KnowledgeContentType,
    KnowledgeSourceType,
    KnowledgeStaging,
    KnowledgeStagingStatus,
    KnowledgeVectorStatus,
)
from app.repositories.knowledge import KnowledgeRepository
from app.services.knowledge_deduplication import (
    DedupDecision,
    KnowledgeDeduplicationService,
    choose_semantic_candidate,
    merge_questions,
)


def test_dedup_decision_only_allows_three_explicit_outcomes() -> None:
    assert DedupDecision(decision="merge", reason="同一规则").decision == "merge"
    with pytest.raises(ValidationError):
        DedupDecision(decision="maybe", reason="不确定")


def test_semantic_candidate_respects_threshold_and_chunk_state() -> None:
    chunks = {
        1: SimpleNamespace(
            id=1,
            is_active=True,
            vector_status=KnowledgeVectorStatus.VECTORIZED,
        ),
        2: SimpleNamespace(
            id=2,
            is_active=False,
            vector_status=KnowledgeVectorStatus.VECTORIZED,
        ),
    }
    hits = [VectorSearchHit(2, 0.99), VectorSearchHit(1, 0.91)]

    assert choose_semantic_candidate(hits, chunks, min_score=0.9).id == 1
    assert choose_semantic_candidate(hits, chunks, min_score=0.95) is None


def test_merge_questions_is_stable_and_deduplicates_punctuation_variants() -> None:
    merged = merge_questions(["退货怎么办？", "如何退货"], ["退货怎么办?", "怎么申请退货"])
    assert merged == ("如何退货", "怎么申请退货", "退货怎么办?")


class FakeEmbedder:
    dimension = 3

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeVectorStore:
    def __init__(self, target_id: int) -> None:
        self.target_id = target_id

    async def ensure_collection(self) -> None:
        return None

    async def search(self, vector: list[float], *, top_k: int) -> list[VectorSearchHit]:
        return [VectorSearchHit(self.target_id, 0.95)]


class FakeDedupRunnable:
    async def ainvoke(self, messages: object) -> DedupDecision:
        return DedupDecision(decision="merge", reason="答案语义等价")


class FakeDedupModel:
    def with_structured_output(self, schema: object, **kwargs: object) -> FakeDedupRunnable:
        return FakeDedupRunnable()


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="需要真实 MySQL",
)
@pytest.mark.asyncio
async def test_llm_merge_keeps_existing_primary_key_and_marks_it_pending() -> None:
    runtime = create_database_runtime(Settings())
    suffix = uuid4().hex
    conversation_id = f"test-dedup-{suffix}"
    source_key = f"test:dedup:{suffix}"
    existing_draft = KnowledgeDraft(
        source_type=KnowledgeSourceType.MARKDOWN,
        source_key=source_key,
        source_revision="r1",
        category="配送政策",
        questions=("运费规则",),
        answer="普通订单满九十九元免基础配送费。",
        section_path=("配送政策", "运费规则"),
        content_type=KnowledgeContentType.POLICY,
    )
    incoming_draft = KnowledgeDraft(
        source_type=KnowledgeSourceType.CONVERSATION,
        source_key=f"conversation:{conversation_id}:1-2:0",
        source_revision="r2",
        category="配送政策",
        questions=("邮费是多少",),
        answer="订单金额达到九十九元即可免基础运费。",
        section_path=("历史客服对话", "配送政策"),
        content_type=KnowledgeContentType.CONVERSATION_QA,
    )
    try:
        async with runtime.session_factory.begin() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    user_id="test-user",
                    status=ConversationStatus.ACTIVE,
                )
            )
            existing = (await KnowledgeRepository(session).upsert_chunk(existing_draft)).chunk
            existing.vector_status = KnowledgeVectorStatus.VECTORIZED
            existing.vector_id = str(existing.id)
            session.add(
                KnowledgeStaging(
                    conversation_id=conversation_id,
                    first_message_id=1,
                    last_message_id=2,
                    item_index=0,
                    category=incoming_draft.category,
                    questions=list(incoming_draft.questions),
                    answer=incoming_draft.answer,
                    is_critical=False,
                    content_fingerprint=build_content_fingerprint(incoming_draft),
                    status=KnowledgeStagingStatus.EXTRACTED,
                )
            )
            existing_id = existing.id

        service = KnowledgeDeduplicationService(
            session_factory=runtime.session_factory,
            embedder=FakeEmbedder(),
            vector_store=FakeVectorStore(existing_id),
            model=FakeDedupModel(),
            candidate_score=0.9,
        )
        result = await service.run_once()

        assert result.merged == 1
        async with runtime.session_factory() as session:
            existing = await session.get(KnowledgeChunk, existing_id)
            staging = await session.scalar(
                select(KnowledgeStaging).where(
                    KnowledgeStaging.conversation_id == conversation_id
                )
            )
            assert existing is not None
            assert existing.source_key == source_key
            assert set(existing.questions) == {"运费规则", "邮费是多少"}
            assert existing.vector_status is KnowledgeVectorStatus.PENDING
            assert staging is not None
            assert staging.status is KnowledgeStagingStatus.MERGED
            assert staging.promoted_chunk_id == existing_id
    finally:
        async with runtime.session_factory.begin() as session:
            await session.execute(
                delete(KnowledgeStaging).where(
                    KnowledgeStaging.conversation_id == conversation_id
                )
            )
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.source_key == source_key)
            )
            await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
        await runtime.dispose()
