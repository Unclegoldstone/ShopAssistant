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
    history_max_tokens: int = Field(default=3000, gt=0)
    model_timeout_seconds: float = Field(default=60, gt=0)
    frontend_origin: AnyHttpUrl = "http://localhost:5173"

