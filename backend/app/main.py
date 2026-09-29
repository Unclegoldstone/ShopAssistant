from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.extraction import router as extraction_router
from app.config import Settings
from app.conversation_store import ConversationStore
from app.model_factory import create_chat_model
from app.services.chat import ChatService
from app.services.extraction import ExtractionService


def create_app(*, settings: Settings | None = None, model: Any | None = None) -> FastAPI:
    runtime_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime_model = model or create_chat_model(runtime_settings)
        store = ConversationStore()
        app.state.settings = runtime_settings
        app.state.chat_service = ChatService(
            runtime_model,
            store,
            model_name=runtime_settings.model_name,
            history_max_tokens=runtime_settings.history_max_tokens,
        )
        app.state.extraction_service = ExtractionService(runtime_model)
        yield

    app = FastAPI(title="Shop Assistant", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(runtime_settings.frontend_origin).rstrip("/")],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(chat_router)
    app.include_router(extraction_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
