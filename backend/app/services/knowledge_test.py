from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path, PurePath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.knowledge.markdown import MarkdownKnowledgeSplitter
from app.knowledge.test_schemas import (
    KbChunkPreview,
    KbIngestResponse,
    KbPreviewResponse,
)
from app.knowledge.types import KnowledgeDraft
from app.models import (
    KnowledgeChunk,
    KnowledgeMiningRun,
    KnowledgeSourceType,
    KnowledgeStaging,
)
from app.repositories.knowledge import KnowledgeRepository
from app.services.knowledge_retrieval import KnowledgeRetrievalService
from app.services.knowledge_vectorization import (
    FailureHook,
    KnowledgeVectorizationWorker,
    VectorizationResult,
)


class KnowledgeUploadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class KnowledgeTestUnavailableError(RuntimeError):
    pass


class KnowledgeFaultInjected(RuntimeError):
    pass


WorkerFactory = Callable[[FailureHook | None], KnowledgeVectorizationWorker]


class KnowledgeTestService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None,
        splitter: MarkdownKnowledgeSplitter,
        upload_max_bytes: int,
        worker_factory: WorkerFactory | None = None,
        retrieval: KnowledgeRetrievalService | None = None,
        pipeline: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._splitter = splitter
        self._upload_max_bytes = upload_max_bytes
        self._worker_factory = worker_factory
        self._retrieval = retrieval
        self._pipeline = pipeline

    @property
    def upload_max_bytes(self) -> int:
        return self._upload_max_bytes

    def preview(self, filename: str, content: bytes) -> KbPreviewResponse:
        safe_name = self._validate_upload(filename, content)
        try:
            markdown = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KnowledgeUploadError("invalid_encoding", "Markdown 必须使用 UTF-8 编码") from exc
        chunks = self._splitter.split(safe_name, markdown)
        return KbPreviewResponse(
            file_name=safe_name,
            byte_count=len(content),
            char_count=len(markdown),
            chunk_count=len(chunks),
            chunks=[
                KbChunkPreview(
                    ordinal=chunk.ordinal,
                    char_count=chunk.char_count,
                    content_type=chunk.content_type.value,
                    section_path=list(chunk.section_path),
                    category=chunk.category,
                    questions=list(chunk.questions),
                    answer=chunk.answer,
                    is_table=chunk.is_table,
                    is_critical=chunk.is_critical,
                    warning=chunk.warning,
                    previous_ordinal=chunk.previous_ordinal,
                    next_ordinal=chunk.next_ordinal,
                )
                for chunk in chunks
            ],
        )

    async def ingest(self, filename: str, content: bytes) -> KbIngestResponse:
        session_factory = self._require_database()
        preview = self.preview(filename, content)
        markdown = content.decode("utf-8")
        raw_chunks = self._splitter.split(preview.file_name, markdown)
        prefix = f"kb_upload:{preview.file_name}:"
        drafts = [
            KnowledgeDraft(
                source_type=KnowledgeSourceType.MARKDOWN,
                source_key=f"{prefix}{'/'.join(chunk.section_path)}:{chunk.ordinal}",
                source_revision=chunk.source_revision,
                category=chunk.category,
                questions=chunk.questions,
                answer=chunk.answer,
                section_path=chunk.section_path,
                content_type=chunk.content_type,
                is_critical=chunk.is_critical,
            )
            for chunk in raw_chunks
        ]
        async with session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            results = [await repository.upsert_chunk(draft) for draft in drafts]
            for index, result in enumerate(results):
                await repository.set_neighbors(
                    result.chunk.id,
                    previous_chunk_id=results[index - 1].chunk.id if index > 0 else None,
                    next_chunk_id=(
                        results[index + 1].chunk.id if index + 1 < len(results) else None
                    ),
                )
            active_keys = {draft.source_key for draft in drafts}
            old_chunks = list(
                await session.scalars(
                    select(KnowledgeChunk).where(KnowledgeChunk.source_key.like(f"{prefix}%"))
                )
            )
            deactivated = 0
            for chunk in old_chunks:
                if chunk.source_key not in active_keys and chunk.is_active:
                    await repository.mark_pending_delete(chunk.id)
                    deactivated += 1
        created = sum(result.created for result in results)
        changed = sum(result.changed and not result.created for result in results)
        return KbIngestResponse(
            source_name=preview.file_name,
            chunk_ids=[result.chunk.id for result in results],
            created=created,
            changed=changed,
            unchanged=len(results) - created - changed,
            deactivated=deactivated,
        )

    async def vectorize(self, fault_stage: str | None = None) -> VectorizationResult:
        if self._worker_factory is None:
            raise KnowledgeTestUnavailableError("向量运行时不可用")
        fired = False

        def inject(stage: str, chunk_id: int, index: int) -> None:
            nonlocal fired
            if fault_stage == stage and not fired:
                fired = True
                raise KnowledgeFaultInjected(f"已在 {stage} 注入一次测试故障")

        worker = self._worker_factory(inject if fault_stage else None)
        if fault_stage:
            session_factory = self._require_database()
            async with session_factory() as session:
                chunk_ids = list(
                    await session.scalars(
                        select(KnowledgeChunk.id).where(
                            KnowledgeChunk.source_key.like("kb_upload:%")
                        )
                    )
                )
            return await worker.run_once(chunk_ids=chunk_ids)
        total = VectorizationResult()
        while True:
            current = await worker.run_once()
            total = VectorizationResult(
                claimed=total.claimed + current.claimed,
                vectorized=total.vectorized + current.vectorized,
                failed=total.failed + current.failed,
                deleted=total.deleted + current.deleted,
            )
            if current.claimed == 0:
                return total

    async def search(self, query: str, *, top_k: int) -> list[dict[str, object]]:
        if self._retrieval is None:
            raise KnowledgeTestUnavailableError("检索运行时不可用")
        return [
            asdict(match)
            for match in await self._retrieval.search(query, top_k=top_k)
        ]

    async def run_pipeline(self) -> Any:
        if self._pipeline is None:
            raise KnowledgeTestUnavailableError("对话挖取运行时不可用")
        return await self._pipeline.run_once()

    async def snapshot(self) -> dict[str, object]:
        session_factory = self._require_database()
        async with session_factory() as session:
            chunks = list(
                await session.scalars(
                    select(KnowledgeChunk).order_by(KnowledgeChunk.id.desc()).limit(100)
                )
            )
            staging = list(
                await session.scalars(
                    select(KnowledgeStaging).order_by(KnowledgeStaging.id.desc()).limit(100)
                )
            )
            runs = list(
                await session.scalars(
                    select(KnowledgeMiningRun).order_by(KnowledgeMiningRun.id.desc()).limit(50)
                )
            )
            status_rows = (
                await session.execute(
                    select(KnowledgeChunk.vector_status, func.count())
                    .group_by(KnowledgeChunk.vector_status)
                    .order_by(KnowledgeChunk.vector_status)
                )
            ).all()
        return {
            "status": {status.value: count for status, count in status_rows},
            "chunks": [_chunk_dict(item) for item in chunks],
            "staging": [_staging_dict(item) for item in staging],
            "runs": [_run_dict(item) for item in runs],
        }

    def _validate_upload(self, filename: str, content: bytes) -> str:
        unsafe = (
            not filename
            or PurePath(filename).name != filename
            or "/" in filename
            or "\\" in filename
        )
        if unsafe:
            raise KnowledgeUploadError("unsafe_filename", "文件名不能包含路径")
        if Path(filename).suffix.lower() != ".md":
            raise KnowledgeUploadError("invalid_extension", "只允许上传 .md 文件")
        if not content:
            raise KnowledgeUploadError("empty_file", "Markdown 文件不能为空")
        if len(content) > self._upload_max_bytes:
            raise KnowledgeUploadError("file_too_large", "Markdown 文件超过上传大小限制")
        return filename

    def _require_database(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise KnowledgeTestUnavailableError("数据库运行时不可用")
        return self._session_factory


def _chunk_dict(item: KnowledgeChunk) -> dict[str, object]:
    return {
        "id": item.id,
        "source_key": item.source_key,
        "category": item.category,
        "questions": item.questions,
        "answer": item.answer,
        "content_type": item.content_type.value,
        "is_critical": item.is_critical,
        "vector_status": item.vector_status.value,
        "vector_attempts": item.vector_attempts,
        "vector_error": item.vector_error,
        "is_active": item.is_active,
    }


def _staging_dict(item: KnowledgeStaging) -> dict[str, object]:
    return {
        "id": item.id,
        "conversation_id": item.conversation_id,
        "questions": item.questions,
        "answer": item.answer,
        "status": item.status.value,
        "decision_reason": item.decision_reason,
        "promoted_chunk_id": item.promoted_chunk_id,
    }


def _run_dict(item: KnowledgeMiningRun) -> dict[str, object]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "status": item.status.value,
        "cursor_start_message_id": item.cursor_start_message_id,
        "cursor_end_message_id": item.cursor_end_message_id,
        "extracted_count": item.extracted_count,
        "promoted_count": item.promoted_count,
        "error_summary": item.error_summary,
    }
