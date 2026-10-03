from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from app.config import Settings
from app.db.session import DatabaseRuntime, create_database_runtime
from app.knowledge.embedding import BgeM3Embedder
from app.knowledge.vector_store import MilvusKnowledgeStore
from app.model_factory import create_chat_model
from app.repositories.knowledge import sanitize_error_summary
from app.services.conversation_mining import ConversationMiningService
from app.services.knowledge_deduplication import KnowledgeDeduplicationService
from app.services.knowledge_vectorization import KnowledgeVectorizationWorker


@dataclass(frozen=True, slots=True)
class PipelineResult:
    stages: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


class KnowledgePipeline:
    def __init__(self, *, mining: Any, deduplication: Any, vectorization: Any) -> None:
        self._mining = mining
        self._deduplication = deduplication
        self._vectorization = vectorization

    async def run_once(self) -> PipelineResult:
        stages: dict[str, Any] = {}
        errors: dict[str, str] = {}
        operations = (
            ("mine", self._mining.run_once),
            ("deduplicate", self._deduplication.run_once),
            ("vectorize", self._vectorization.run_until_idle),
        )
        for name, operation in operations:
            try:
                stages[name] = await operation()
            except Exception as exc:
                errors[name] = (
                    f"{type(exc).__name__}: {sanitize_error_summary(exc)}"
                )
        return PipelineResult(stages=stages, errors=errors)


@dataclass(slots=True)
class KnowledgePipelineRuntime:
    database: DatabaseRuntime
    pipeline: KnowledgePipeline

    async def close(self) -> None:
        await self.database.dispose()


def create_pipeline_runtime(settings: Settings | None = None) -> KnowledgePipelineRuntime:
    settings = settings or Settings()
    database = create_database_runtime(settings)
    model = create_chat_model(settings)
    embedder = BgeM3Embedder(
        model_name_or_path=settings.bge_model_name_or_path,
        device=settings.bge_offline_device,
        use_fp16=settings.bge_use_fp16,
        batch_size=settings.bge_batch_size,
        max_length=settings.bge_max_length,
    )
    vector_store = MilvusKnowledgeStore(
        uri=str(settings.milvus_uri),
        token=settings.milvus_token.get_secret_value(),
        database=settings.milvus_database,
        collection=settings.milvus_collection,
        dimension=embedder.dimension,
        timeout_seconds=settings.milvus_timeout_seconds,
    )
    mining = ConversationMiningService(
        session_factory=database.session_factory,
        model=model,
        batch_size=settings.knowledge_mining_batch_size,
        token_budget=settings.knowledge_mining_token_budget,
    )
    deduplication = KnowledgeDeduplicationService(
        session_factory=database.session_factory,
        embedder=embedder,
        vector_store=vector_store,
        model=model,
        candidate_score=settings.knowledge_dedup_candidate_score,
    )
    vectorization = KnowledgeVectorizationWorker(
        session_factory=database.session_factory,
        embedder=embedder,
        vector_store=vector_store,
        embedding_model=settings.bge_model_name_or_path,
        embedding_version=settings.bge_model_name_or_path,
        batch_size=settings.knowledge_vector_batch_size,
        lease_timeout=timedelta(seconds=settings.knowledge_vector_lease_seconds),
        max_attempts=settings.knowledge_vector_max_attempts,
    )
    return KnowledgePipelineRuntime(
        database=database,
        pipeline=KnowledgePipeline(
            mining=mining,
            deduplication=deduplication,
            vectorization=vectorization,
        ),
    )
