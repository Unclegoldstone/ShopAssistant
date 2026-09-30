from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.conversation_history import router as conversation_history_router
from app.api.database_test import router as database_test_router
from app.api.extraction import router as extraction_router
from app.api.faq_crud import router as faq_crud_router
from app.api.table_crud import router as table_crud_router
from app.config import Settings
from app.conversation_store import ConversationStore
from app.db.session import create_database_runtime
from app.model_factory import create_chat_model
from app.services.chat import ChatService
from app.services.conversation_history import ConversationHistoryService
from app.services.database_test import DatabaseTestService
from app.services.extraction import ExtractionService
from app.services.faq_crud import FaqCrudService
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
        tool_registry = ToolRegistry(build_business_tools(database_runtime.session_factory))
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
