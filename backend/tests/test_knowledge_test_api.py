from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeStreamingModel
from tests.test_chat_api import make_settings


def test_kb_preview_accepts_utf8_markdown_and_does_not_require_vector_runtime() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))
    with TestClient(app) as client:
        response = client.post(
            "/v1/tests/knowledge/preview",
            files={
                "file": (
                    "shipping.md",
                    "# 配送\n\n## 运费\n\n满 99 元免运费。",
                    "text/markdown",
                )
            },
        )

    assert response.status_code == 200
    assert response.json()["file_name"] == "shipping.md"
    assert response.json()["chunks"][0]["section_path"] == ["配送", "运费"]


def test_kb_preview_returns_stable_safe_error_for_bad_file() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))
    with TestClient(app) as client:
        response = client.post(
            "/v1/tests/knowledge/preview",
            files={"file": ("secret.txt", b"secret", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_extension"
    assert "secret" not in response.json()["detail"]["message"]


def test_kb_search_validates_custom_top_k_before_runtime_execution() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))
    with TestClient(app) as client:
        response = client.post(
            "/v1/tests/knowledge/search",
            json={"query": "邮费是多少", "top_k": 0},
        )

    assert response.status_code == 422
