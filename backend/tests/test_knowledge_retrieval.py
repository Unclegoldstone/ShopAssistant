from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.knowledge.vector_store import VectorSearchHit
from app.models import KnowledgeVectorStatus
from app.services.knowledge_retrieval import KnowledgeRetrievalService


class FakeEmbedder:
    dimension = 3

    async def embed(self, texts: list[str]) -> list[list[float]]:
        assert texts == ["邮费是多少"]
        return [[1.0, 0.0, 0.0]]


class FakeVectorStore:
    def __init__(self) -> None:
        self.requested_top_k: list[int] = []

    async def search(self, vector: list[float], *, top_k: int) -> list[VectorSearchHit]:
        self.requested_top_k.append(top_k)
        return [
            VectorSearchHit(3, 0.95),
            VectorSearchHit(2, 0.88),
            VectorSearchHit(1, 0.70),
        ]


@pytest.mark.asyncio
async def test_retrieval_preserves_rank_and_filters_score_and_chunk_state() -> None:
    chunks = {
        3: SimpleNamespace(
            id=3,
            category="配送政策",
            questions=["运费规则", "配送费用"],
            answer="满 99 元免基础配送费。",
            is_active=True,
            vector_status=KnowledgeVectorStatus.VECTORIZED,
        ),
        2: SimpleNamespace(
            id=2,
            category="旧政策",
            questions=["旧运费"],
            answer="旧答案",
            is_active=False,
            vector_status=KnowledgeVectorStatus.VECTORIZED,
        ),
        1: SimpleNamespace(
            id=1,
            category="其他",
            questions=["低分"],
            answer="低分答案",
            is_active=True,
            vector_status=KnowledgeVectorStatus.VECTORIZED,
        ),
    }

    async def load(ids: list[int]):  # noqa: ANN202
        return [chunks[item_id] for item_id in ids if item_id in chunks]

    vector_store = FakeVectorStore()
    service = KnowledgeRetrievalService(
        session_factory=None,
        embedder=FakeEmbedder(),
        vector_store=vector_store,
        top_k=3,
        min_score=0.75,
        chunk_loader=load,
    )

    matches = await service.search("邮费是多少")

    assert len(matches) == 1
    assert matches[0].chunk_id == 3
    assert matches[0].question == "运费规则 / 配送费用"
    assert matches[0].score == pytest.approx(0.95)
    assert vector_store.requested_top_k == [3]


@pytest.mark.asyncio
async def test_retrieval_allows_test_page_to_override_top_k() -> None:
    async def load(ids: list[int]):  # noqa: ANN202
        return []

    vector_store = FakeVectorStore()
    service = KnowledgeRetrievalService(
        session_factory=None,
        embedder=FakeEmbedder(),
        vector_store=vector_store,
        top_k=3,
        min_score=0.75,
        chunk_loader=load,
    )

    await service.search("邮费是多少", top_k=8)

    assert vector_store.requested_top_k == [8]
