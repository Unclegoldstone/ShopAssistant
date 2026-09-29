from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fakes import FakeStreamingModel


def make_settings(**overrides: object) -> Settings:
    values = {
        "model_base_url": "https://example.test/v1",
        "model_name": "qwen-test",
        "model_api_key": "secret-value",
        "history_max_tokens": 100,
        "frontend_origin": "http://localhost:5173",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def chat_payload(**overrides: object) -> dict:
    payload = {
        "model": "qwen-test",
        "conversation_id": "api-test",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": True,
    }
    payload.update(overrides)
    return payload


def test_health_endpoint() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_models_endpoint_exposes_only_configured_model() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))

    with TestClient(app) as client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {
                "id": "qwen-test",
                "object": "model",
                "created": 0,
                "owned_by": "aliyun",
            }
        ],
    }


def test_chat_endpoint_returns_openai_sse_stream_and_headers() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([["你", "好"]]))

    with TestClient(app) as client:
        response = client.post("/v1/chat/completions", json=chat_payload())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert '"object":"chat.completion.chunk"' in response.text
    assert response.text.endswith("data: [DONE]\n\n")


def test_model_name_must_match_server_configuration() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json=chat_payload(model="another-model"),
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "model_mismatch"


def test_invalid_chat_shapes_return_validation_error() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))

    with TestClient(app) as client:
        invalid_role = client.post(
            "/v1/chat/completions",
            json=chat_payload(messages=[{"role": "assistant", "content": "x"}]),
        )
        non_stream = client.post(
            "/v1/chat/completions",
            json=chat_payload(stream=False),
        )

    assert invalid_role.status_code == 422
    assert non_stream.status_code == 422


def test_over_budget_current_input_returns_413_before_stream_starts() -> None:
    settings = make_settings(history_max_tokens=2)
    app = create_app(settings=settings, model=FakeStreamingModel([]))

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json=chat_payload(messages=[{"role": "user", "content": "这是明显过长的输入"}]),
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "input_too_long"


def test_cors_allows_only_configured_frontend_origin() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))

    with TestClient(app) as client:
        allowed = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        denied = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers
