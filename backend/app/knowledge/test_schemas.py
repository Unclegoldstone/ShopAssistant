from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KbChunkPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordinal: int
    char_count: int
    content_type: str
    section_path: list[str]
    category: str
    questions: list[str]
    answer: str
    is_table: bool
    is_critical: bool
    warning: str | None
    previous_ordinal: int | None
    next_ordinal: int | None


class KbPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str
    byte_count: int
    char_count: int
    chunk_count: int
    chunks: list[KbChunkPreview]


class KbIngestResponse(BaseModel):
    source_name: str
    chunk_ids: list[int]
    created: int
    changed: int
    unchanged: int
    deactivated: int


class KbVectorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fault_stage: Literal["before_upsert", "after_upsert"] | None = None


class KbSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=100)
