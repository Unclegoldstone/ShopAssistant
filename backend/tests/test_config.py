from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

MODEL_ENV_NAMES = ("MODEL_BASE_URL", "MODEL_NAME", "MODEL_API_KEY")


def clear_model_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in MODEL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_missing_model_configuration_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_model_environment(monkeypatch)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_load_from_dotenv(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_model_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MODEL_BASE_URL=https://example.test/compatible-mode/v1\n"
        "MODEL_NAME=qwen-test\n"
        "MODEL_API_KEY=secret-value\n"
        "HISTORY_MAX_TOKENS=2048\n"
        "MODEL_TIMEOUT_SECONDS=45\n"
        "FRONTEND_ORIGIN=http://localhost:5173\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert str(settings.model_base_url) == "https://example.test/compatible-mode/v1"
    assert settings.model_name == "qwen-test"
    assert settings.model_api_key.get_secret_value() == "secret-value"
    assert settings.history_max_tokens == 2048
    assert settings.model_timeout_seconds == 45


@pytest.mark.parametrize(
    ("field", "value"),
    [("history_max_tokens", 0), ("model_timeout_seconds", -1)],
)
def test_positive_numeric_settings_are_required(field: str, value: int) -> None:
    values = {
        "model_base_url": "https://example.test/v1",
        "model_name": "qwen-test",
        "model_api_key": "secret-value",
        field: value,
    }

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_api_key_is_not_exposed_in_repr() -> None:
    settings = Settings(
        _env_file=None,
        model_base_url="https://example.test/v1",
        model_name="qwen-test",
        model_api_key="do-not-leak",
    )

    assert "do-not-leak" not in repr(settings)
