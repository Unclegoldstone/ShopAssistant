from __future__ import annotations

from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Validated runtime settings loaded from the project-level .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    model_base_url: AnyHttpUrl
    model_name: str = Field(min_length=1)
    model_api_key: SecretStr
    database_url: SecretStr = SecretStr(
        "mysql+asyncmy://shop_assistant:shop_assistant_dev@127.0.0.1:3306/shop_assistant"
    )
    history_max_tokens: int = Field(default=3000, gt=0)
    model_timeout_seconds: float = Field(default=60, gt=0)
    tool_timeout_seconds: float = Field(default=5, gt=0)
    tool_max_attempts: int = Field(default=2, ge=1, le=5)
    frontend_origin: AnyHttpUrl = "http://localhost:5173"
