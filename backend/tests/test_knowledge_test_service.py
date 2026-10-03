from __future__ import annotations

import os
from datetime import timedelta

import pytest
from sqlalchemy import delete

from app.config import Settings
from app.db.session import create_database_runtime
from app.knowledge.markdown import MarkdownKnowledgeSplitter
from app.knowledge.test_schemas import KbSearchRequest
from app.knowledge.vector_store import VectorRecord
from app.models import KnowledgeChunk, KnowledgeVectorStatus
from app.services.knowledge_test import KnowledgeTestService, KnowledgeUploadError
from app.services.knowledge_vectorization import (
    KnowledgeVectorizationWorker,
    VectorizationResult,
)


def build_service(max_bytes: int = 1024) -> KnowledgeTestService:
    return KnowledgeTestService(
        session_factory=None,
        splitter=MarkdownKnowledgeSplitter(chunk_size=80, chunk_overlap=10),
        upload_max_bytes=max_bytes,
    )


def test_preview_returns_chunk_metadata_without_runtime_dependencies() -> None:
    service = build_service()
    content = "# 配送政策\n\n## 运费规则\n\n满 99 元免基础配送费。".encode()

    preview = service.preview("shipping.md", content)

    assert preview.file_name == "shipping.md"
    assert preview.byte_count == len(content)
    assert preview.char_count > 0
    assert preview.chunks[0].content_type == "policy"
    assert preview.chunks[0].section_path == ["配送政策", "运费规则"]
    assert preview.chunks[0].questions == ["运费规则"]
    assert preview.chunks[0].char_count == len(preview.chunks[0].answer)


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        ("note.txt", b"text", "invalid_extension"),
        ("../secret.md", b"text", "unsafe_filename"),
        ("empty.md", b"", "empty_file"),
        ("binary.md", b"\xff\xfe", "invalid_encoding"),
        ("large.md", b"x" * 20, "file_too_large"),
    ],
)
def test_preview_rejects_invalid_uploads(filename: str, content: bytes, code: str) -> None:
    service = build_service(max_bytes=10)
    with pytest.raises(KnowledgeUploadError) as captured:
        service.preview(filename, content)
    assert captured.value.code == code


@pytest.mark.parametrize("top_k", [0, 101])
def test_kb_search_rejects_out_of_range_top_k(top_k: int) -> None:
    with pytest.raises(ValueError):
        KbSearchRequest(query="邮费是多少", top_k=top_k)


def test_kb_search_accepts_custom_top_k() -> None:
    assert KbSearchRequest(query="邮费是多少", top_k=12).top_k == 12


@pytest.mark.asyncio
async def test_normal_vector_compensation_is_not_limited_to_kb_upload() -> None:
    class RecordingWorker:
        def __init__(self) -> None:
            self.calls: list[list[int] | None] = []

        async def run_once(
            self, *, chunk_ids: list[int] | None = None
        ) -> VectorizationResult:
            self.calls.append(chunk_ids)
            if len(self.calls) == 1:
                return VectorizationResult(claimed=1, vectorized=1)
            return VectorizationResult()

    worker = RecordingWorker()

    def unexpected_session_factory():  # noqa: ANN202
        pytest.fail("普通向量补偿不应查询 kb_upload 限定 ID")

    service = KnowledgeTestService(
        session_factory=unexpected_session_factory,  # type: ignore[arg-type]
        splitter=MarkdownKnowledgeSplitter(chunk_size=80, chunk_overlap=10),
        upload_max_bytes=1024,
        worker_factory=lambda _hook: worker,  # type: ignore[arg-type,return-value]
    )

    result = await service.vectorize()

    assert result.vectorized == 1
    assert worker.calls == [None, None]


class _FakeEmbedder:
    dimension = 3

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.0] for text in texts]


class _FakeVectorStore:
    def __init__(self) -> None:
        self.records: dict[int, VectorRecord] = {}

    async def ensure_collection(self) -> None:
        return None

    async def upsert(self, records: list[VectorRecord]) -> None:
        self.records.update({record.chunk_id: record for record in records})

    async def search(self, vector: list[float], *, top_k: int):  # noqa: ANN201
        return []

    async def delete(self, chunk_ids: list[int]) -> None:
        for chunk_id in chunk_ids:
            self.records.pop(chunk_id, None)


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="需要真实 MySQL",
)
@pytest.mark.asyncio
async def test_kb_fault_injection_stops_then_next_run_recovers() -> None:
    runtime = create_database_runtime(Settings())
    store = _FakeVectorStore()

    def worker_factory(hook):  # noqa: ANN001, ANN202
        return KnowledgeVectorizationWorker(
            session_factory=runtime.session_factory,
            embedder=_FakeEmbedder(),
            vector_store=store,
            embedding_model="fake-bge",
            embedding_version="v1",
            batch_size=10,
            lease_timeout=timedelta(seconds=0),
            max_attempts=3,
            failure_hook=hook,
        )

    service = KnowledgeTestService(
        session_factory=runtime.session_factory,
        splitter=MarkdownKnowledgeSplitter(chunk_size=80, chunk_overlap=10),
        upload_max_bytes=1024,
        worker_factory=worker_factory,
    )
    chunk_ids: list[int] = []
    try:
        ingested = await service.ingest(
            "fault-recovery.md",
            "# 配送政策\n\n## 运费规则\n\n满 99 元免基础配送费。".encode(),
        )
        chunk_ids = ingested.chunk_ids

        failed = await service.vectorize("after_upsert")
        assert failed.claimed == 1
        assert failed.failed == 1
        async with runtime.session_factory() as session:
            chunk = await session.get(KnowledgeChunk, chunk_ids[0])
            assert chunk is not None
            assert chunk.vector_status is KnowledgeVectorStatus.FAILED

        recovered = await service.vectorize()
        assert recovered.vectorized >= 1
        assert chunk_ids[0] in store.records
        async with runtime.session_factory() as session:
            chunk = await session.get(KnowledgeChunk, chunk_ids[0])
            assert chunk is not None
            assert chunk.vector_status is KnowledgeVectorStatus.VECTORIZED
            assert chunk.vector_attempts == 2
    finally:
        if chunk_ids:
            async with runtime.session_factory.begin() as session:
                await session.execute(
                    delete(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids))
                )
        await runtime.dispose()
