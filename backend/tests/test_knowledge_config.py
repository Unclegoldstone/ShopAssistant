from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def settings_values() -> dict[str, object]:
    return {
        "model_base_url": "https://example.test/v1",
        "model_name": "qwen-test",
        "model_api_key": "secret-value",
        "database_url": "mysql+asyncmy://shop:db-secret@localhost:3306/shop_assistant",
    }


def test_knowledge_settings_have_safe_defaults() -> None:
    settings = Settings(_env_file=None, **settings_values())

    assert settings.bge_model_name_or_path == "BAAI/bge-m3"
    assert settings.bge_online_device == "cuda"
    assert settings.bge_offline_device == "cpu"
    assert settings.bge_use_fp16 is True
    assert settings.bge_batch_size == 2
    assert settings.bge_max_length == 1024
    assert str(settings.milvus_uri) == "http://127.0.0.1:19530/"
    assert settings.milvus_token.get_secret_value() == "root:Milvus"
    assert settings.milvus_database == "default"
    assert settings.milvus_collection == "knowledge"
    assert settings.knowledge_top_k == 5
    assert settings.knowledge_min_score == pytest.approx(0.5)
    assert settings.knowledge_chunk_size == 1000
    assert settings.knowledge_chunk_overlap == 120
    assert settings.knowledge_vector_batch_size == 4
    assert settings.knowledge_vector_lease_seconds == 300
    assert settings.knowledge_vector_max_attempts == 3
    assert settings.knowledge_mining_interval_minutes == 60
    assert settings.knowledge_mining_batch_size == 5
    assert settings.knowledge_mining_token_budget == 6000
    assert settings.knowledge_dedup_candidate_score == pytest.approx(0.9)
    assert settings.kb_upload_max_bytes == 2 * 1024 * 1024


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bge_batch_size", 0),
        ("bge_max_length", 8193),
        ("knowledge_top_k", 0),
        ("knowledge_min_score", 1.1),
        ("knowledge_chunk_size", 0),
        ("knowledge_chunk_overlap", -1),
        ("knowledge_vector_batch_size", 0),
        ("knowledge_vector_lease_seconds", 0),
        ("knowledge_vector_max_attempts", 0),
        ("knowledge_mining_interval_minutes", 0),
        ("knowledge_mining_batch_size", 0),
        ("knowledge_mining_token_budget", 0),
        ("knowledge_dedup_candidate_score", -1.1),
        ("kb_upload_max_bytes", 0),
    ],
)
def test_knowledge_numeric_settings_are_bounded(field: str, value: int | float) -> None:
    values = settings_values()
    values[field] = value

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_chunk_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            **settings_values(),
            knowledge_chunk_size=100,
            knowledge_chunk_overlap=100,
        )


def test_milvus_token_is_not_exposed_in_repr() -> None:
    settings = Settings(
        _env_file=None,
        **settings_values(),
        milvus_token="do-not-leak",
    )

    assert "do-not-leak" not in repr(settings)
