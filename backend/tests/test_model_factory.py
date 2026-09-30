from __future__ import annotations

from unittest.mock import patch

from app.config import Settings
from app.model_factory import create_chat_model


def test_model_factory_forwards_validated_settings() -> None:
    settings = Settings(
        _env_file=None,
        model_base_url="https://example.test/compatible-mode/v1",
        model_name="qwen-test",
        model_api_key="top-secret",
        model_timeout_seconds=23,
    )

    with patch("app.model_factory.ChatOpenAI") as chat_openai:
        model = create_chat_model(settings)

    assert model is chat_openai.return_value
    chat_openai.assert_called_once_with(
        model="qwen-test",
        base_url="https://example.test/compatible-mode/v1",
        api_key="top-secret",
        timeout=23,
        max_retries=2,
    )
    assert "top-secret" not in repr(settings)
