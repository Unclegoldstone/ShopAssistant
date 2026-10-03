from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
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

    bge_model_name_or_path: str = Field(default="BAAI/bge-m3", min_length=1)
    bge_online_device: Literal["cpu", "cuda"] = "cuda"
    bge_offline_device: Literal["cpu", "cuda"] = "cpu"
    bge_use_fp16: bool = True
    bge_batch_size: int = Field(default=2, gt=0, le=128)
    bge_max_length: int = Field(default=1024, gt=0, le=8192)

    milvus_uri: AnyHttpUrl = "http://127.0.0.1:19530"
    milvus_token: SecretStr = SecretStr("root:Milvus")
    milvus_database: str = Field(default="default", min_length=1, max_length=255)
    milvus_collection: str = Field(
        default="knowledge",
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    milvus_timeout_seconds: float = Field(default=10, gt=0)

    knowledge_top_k: int = Field(default=5, gt=0, le=100)
    knowledge_min_score: float = Field(default=0.5, ge=-1, le=1)
    knowledge_chunk_size: int = Field(default=1000, gt=0)
    knowledge_chunk_overlap: int = Field(default=120, ge=0)
    knowledge_vector_batch_size: int = Field(default=4, gt=0, le=256)
    knowledge_vector_lease_seconds: int = Field(default=300, gt=0)
    knowledge_vector_max_attempts: int = Field(default=3, gt=0, le=20)
    knowledge_mining_interval_minutes: int = Field(default=60, gt=0)
    knowledge_mining_batch_size: int = Field(default=5, gt=0, le=1000)
    knowledge_mining_token_budget: int = Field(default=6000, gt=0)
    knowledge_dedup_candidate_score: float = Field(default=0.9, ge=-1, le=1)
    kb_upload_max_bytes: int = Field(default=2 * 1024 * 1024, gt=0)

    @model_validator(mode="after")
    def validate_knowledge_chunk_window(self) -> Settings:
        if self.knowledge_chunk_overlap >= self.knowledge_chunk_size:
            raise ValueError("knowledge_chunk_overlap must be smaller than knowledge_chunk_size")
        return self
