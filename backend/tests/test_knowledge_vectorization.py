from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.config import Settings
from app.db.session import create_database_runtime
from app.knowledge.types import KnowledgeDraft
from app.knowledge.vector_store import VectorRecord
from app.models import (
    KnowledgeChunk,
    KnowledgeContentType,
    KnowledgeSourceType,
    KnowledgeVectorStatus,
)
from app.repositories.knowledge import KnowledgeRepository
from app.services.knowledge_vectorization import KnowledgeVectorizationWorker


class FakeEmbedder:
    dimension = 3

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.0] for text in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self.records: dict[int, VectorRecord] = {}
        self.delete_calls: list[int] = []

    async def ensure_collection(self) -> None:
        return None

    async def upsert(self, records: list[VectorRecord]) -> None:
        self.records.update({record.chunk_id: record for record in records})

    async def search(self, vector: list[float], *, top_k: int):  # noqa: ANN201
        return []

    async def delete(self, chunk_ids: list[int]) -> None:
        for chunk_id in chunk_ids:
            self.delete_calls.append(chunk_id)
            self.records.pop(chunk_id, None)


class SimulatedProcessCrash(BaseException):
    pass


def make_draft(source_key: str) -> KnowledgeDraft:
    return KnowledgeDraft(
        source_type=KnowledgeSourceType.MARKDOWN,
        source_key=source_key,
        source_revision="r1",
        category="配送政策",
        questions=("运费规则",),
        answer="普通订单满九十九元免基础配送费。",
        section_path=("配送政策", "运费规则"),
        content_type=KnowledgeContentType.POLICY,
    )


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="需要真实 MySQL",
)
@pytest.mark.asyncio
async def test_vectorization_recovers_crash_after_milvus_before_mysql_backfill() -> None:
    runtime = create_database_runtime(Settings())
    prefix = f"test:vector-worker:{uuid4().hex}"
    store = FakeVectorStore()
    crash_once = True

    def failure_hook(stage: str, chunk_id: int, index: int) -> None:
        nonlocal crash_once
        if crash_once and stage == "after_upsert":
            crash_once = False
            raise SimulatedProcessCrash()

    worker = KnowledgeVectorizationWorker(
        session_factory=runtime.session_factory,
        embedder=FakeEmbedder(),
        vector_store=store,
        embedding_model="fake-bge",
        embedding_version="v1",
        batch_size=4,
        lease_timeout=timedelta(minutes=5),
        max_attempts=3,
        failure_hook=failure_hook,
    )
    now = datetime.now(UTC).replace(tzinfo=None)

    try:
        async with runtime.session_factory.begin() as session:
            chunk = (await KnowledgeRepository(session).upsert_chunk(make_draft(prefix))).chunk

        with pytest.raises(SimulatedProcessCrash):
            await worker.run_once(now=now, chunk_ids=[chunk.id])
        assert list(store.records) == [chunk.id]

        result = await worker.run_once(
            now=now + timedelta(minutes=6),
            chunk_ids=[chunk.id],
        )
        assert result.vectorized == 1
        assert list(store.records) == [chunk.id]

        async with runtime.session_factory() as session:
            recovered = await KnowledgeRepository(session).get(chunk.id)
            assert recovered is not None
            assert recovered.vector_status is KnowledgeVectorStatus.VECTORIZED
            assert recovered.vector_id == str(chunk.id)
            assert recovered.vector_attempts == 2
    finally:
        async with runtime.session_factory.begin() as session:
            await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_key == prefix))
        await runtime.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="需要真实 MySQL",
)
@pytest.mark.asyncio
async def test_pending_delete_removes_vector_then_clears_vector_id() -> None:
    runtime = create_database_runtime(Settings())
    prefix = f"test:vector-delete:{uuid4().hex}"
    store = FakeVectorStore()
    worker = KnowledgeVectorizationWorker(
        session_factory=runtime.session_factory,
        embedder=FakeEmbedder(),
        vector_store=store,
        embedding_model="fake-bge",
        embedding_version="v1",
        batch_size=4,
        lease_timeout=timedelta(minutes=5),
        max_attempts=3,
    )
    try:
        async with runtime.session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            chunk = (await repository.upsert_chunk(make_draft(prefix))).chunk
            await repository.mark_vectorized(
                chunk.id,
                vector_id=str(chunk.id),
                embedding_model="fake-bge",
                embedding_version="v1",
            )
            await repository.mark_pending_delete(chunk.id)

        result = await worker.run_once(chunk_ids=[chunk.id])

        assert result.deleted == 1
        assert store.delete_calls == [chunk.id]
        async with runtime.session_factory() as session:
            deleted = await KnowledgeRepository(session).get(chunk.id)
            assert deleted is not None
            assert deleted.is_active is False
            assert deleted.vector_status is KnowledgeVectorStatus.PENDING_DELETE
            assert deleted.vector_id is None
    finally:
        async with runtime.session_factory.begin() as session:
            await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_key == prefix))
        await runtime.dispose()
