from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.conversation_history import router as conversation_history_router
from app.api.database_test import router as database_test_router
from app.api.extraction import router as extraction_router
from app.api.faq_crud import router as faq_crud_router
from app.api.knowledge_test import router as knowledge_test_router
from app.api.table_crud import router as table_crud_router
from app.config import Settings
from app.conversation_store import ConversationStore
from app.db.session import create_database_runtime
from app.knowledge.embedding import BgeM3Embedder
from app.knowledge.markdown import MarkdownKnowledgeSplitter
from app.knowledge.vector_store import MilvusKnowledgeStore
from app.model_factory import create_chat_model
from app.services.chat import ChatService
from app.services.conversation_history import ConversationHistoryService
from app.services.conversation_mining import ConversationMiningService
from app.services.database_test import DatabaseTestService
from app.services.extraction import ExtractionService
from app.services.faq_crud import FaqCrudService
from app.services.knowledge_deduplication import KnowledgeDeduplicationService
from app.services.knowledge_pipeline import KnowledgePipeline
from app.services.knowledge_retrieval import KnowledgeRetrievalService
from app.services.knowledge_test import KnowledgeTestService
from app.services.knowledge_vectorization import KnowledgeVectorizationWorker
from app.services.table_crud import TableCrudService
from app.tools.business import build_business_tools
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


def create_app(
    *,
    settings: Settings | None = None,
    model: Any | None = None,
    conversation_store: ConversationStore | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime_model = model or create_chat_model(runtime_settings)
        database_runtime = create_database_runtime(runtime_settings)
        store = conversation_store or ConversationStore(database_runtime.session_factory)
        knowledge_retrieval = None
        vector_store = None
        embedder = None
        if model is None:
            embedder = BgeM3Embedder(
                model_name_or_path=runtime_settings.bge_model_name_or_path,
                device=runtime_settings.bge_online_device,
                use_fp16=runtime_settings.bge_use_fp16,
                batch_size=runtime_settings.bge_batch_size,
                max_length=runtime_settings.bge_max_length,
            )
            vector_store = MilvusKnowledgeStore(
                uri=str(runtime_settings.milvus_uri),
                token=runtime_settings.milvus_token.get_secret_value(),
                database=runtime_settings.milvus_database,
                collection=runtime_settings.milvus_collection,
                dimension=embedder.dimension,
                timeout_seconds=runtime_settings.milvus_timeout_seconds,
            )
            await vector_store.ensure_collection()
            await embedder.embed(["知识库运行状态检查"])
            knowledge_retrieval = KnowledgeRetrievalService(
                session_factory=database_runtime.session_factory,
                embedder=embedder,
                vector_store=vector_store,
                top_k=runtime_settings.knowledge_top_k,
                min_score=runtime_settings.knowledge_min_score,
            )
        splitter = MarkdownKnowledgeSplitter(
            chunk_size=runtime_settings.knowledge_chunk_size,
            chunk_overlap=runtime_settings.knowledge_chunk_overlap,
        )

        def worker_factory(failure_hook: Any = None) -> KnowledgeVectorizationWorker:
            if embedder is None or vector_store is None:
                raise RuntimeError("知识库向量运行时不可用")
            return KnowledgeVectorizationWorker(
                session_factory=database_runtime.session_factory,
                embedder=embedder,
                vector_store=vector_store,
                embedding_model=runtime_settings.bge_model_name_or_path,
                embedding_version=runtime_settings.bge_model_name_or_path,
                batch_size=runtime_settings.knowledge_vector_batch_size,
                lease_timeout=timedelta(
                    seconds=runtime_settings.knowledge_vector_lease_seconds
                ),
                max_attempts=runtime_settings.knowledge_vector_max_attempts,
                failure_hook=failure_hook,
            )

        knowledge_pipeline = None
        if embedder is not None and vector_store is not None:
            knowledge_pipeline = KnowledgePipeline(
                mining=ConversationMiningService(
                    session_factory=database_runtime.session_factory,
                    model=runtime_model,
                    batch_size=runtime_settings.knowledge_mining_batch_size,
                    token_budget=runtime_settings.knowledge_mining_token_budget,
                ),
                deduplication=KnowledgeDeduplicationService(
                    session_factory=database_runtime.session_factory,
                    embedder=embedder,
                    vector_store=vector_store,
                    model=runtime_model,
                    candidate_score=runtime_settings.knowledge_dedup_candidate_score,
                ),
                vectorization=worker_factory(),
            )
        tool_registry = ToolRegistry(
            build_business_tools(
                database_runtime.session_factory,
                knowledge_retrieval=knowledge_retrieval,
            )
        )
        tool_executor = ToolExecutor(
            tool_registry,
            timeout_seconds=runtime_settings.tool_timeout_seconds,
            max_attempts=runtime_settings.tool_max_attempts,
        )
        app.state.settings = runtime_settings
        app.state.database_runtime = database_runtime
        app.state.chat_service = ChatService(
            runtime_model,
            store,
            registry=tool_registry,
            tool_executor=tool_executor,
            model_name=runtime_settings.model_name,
            history_max_tokens=runtime_settings.history_max_tokens,
        )
        app.state.conversation_history_service = ConversationHistoryService(
            database_runtime.session_factory
        )
        app.state.extraction_service = ExtractionService(runtime_model)
        app.state.database_test_service = DatabaseTestService(
            database_runtime.session_factory
        )
        app.state.faq_crud_service = FaqCrudService(database_runtime.session_factory)
        app.state.table_crud_service = TableCrudService(database_runtime.session_factory)
        app.state.knowledge_test_service = KnowledgeTestService(
            session_factory=database_runtime.session_factory,
            splitter=splitter,
            upload_max_bytes=runtime_settings.kb_upload_max_bytes,
            worker_factory=worker_factory if embedder is not None else None,
            retrieval=knowledge_retrieval,
            pipeline=knowledge_pipeline,
        )
        try:
            yield
        finally:
            await database_runtime.dispose()

    app = FastAPI(title="Shop Assistant", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(runtime_settings.frontend_origin).rstrip("/")],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Shop-Assistant-Tool"],
    )
    app.include_router(chat_router)
    app.include_router(conversation_history_router)
    app.include_router(extraction_router)
    app.include_router(database_test_router)
    app.include_router(faq_crud_router)
    app.include_router(table_crud_router)
    app.include_router(knowledge_test_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
