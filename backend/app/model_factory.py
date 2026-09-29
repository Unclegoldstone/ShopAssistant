from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config import Settings


def create_chat_model(settings: Settings) -> ChatOpenAI:
    """Create the single OpenAI-compatible model used by the application."""

    return ChatOpenAI(
        model=settings.model_name,
        base_url=str(settings.model_base_url),
        api_key=settings.model_api_key.get_secret_value(),
        timeout=settings.model_timeout_seconds,
        max_retries=2,
    )

