"""Local API smoke test that never calls the real model provider."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import AfterSalesInfo
from tests.fakes import FakeStreamingModel


def main() -> None:
    settings = Settings(
        _env_file=None,
        model_base_url="https://example.test/v1",
        model_name="qwen-test",
        model_api_key="fake-key",
        history_max_tokens=200,
    )
    model = FakeStreamingModel(
        [["第一轮", "回复"], ["你说的是左耳"]],
        structured_response=AfterSalesInfo(
            order_id="20260928001",
            request_type="换货",
            expected_solution="更换为 42 码",
        ),
    )
    app = create_app(settings=settings, model=model)

    def chat_body(content: str) -> dict:
        return {
            "model": "qwen-test",
            "conversation_id": "smoke-001",
            "messages": [{"role": "user", "content": content}],
            "stream": True,
        }

    with TestClient(app) as client:
        first = client.post("/v1/chat/completions", json=chat_body("左耳没有声音"))
        second = client.post("/v1/chat/completions", json=chat_body("我说的是哪一边？"))
        extracted = client.post(
            "/v1/after-sales/extract",
            json={"text": "订单 20260928001 的鞋小了，想换 42 码"},
        )

    first_lines = [line for line in first.text.splitlines() if line]
    second_context = [message.content for message in model.calls[1]]
    print(f"chat_first_status={first.status_code}")
    print(f"chat_first_first_event={first_lines[0]}")
    print(f"chat_first_last_event={first_lines[-1]}")
    print(f"chat_second_status={second.status_code}")
    print(f"chat_second_context={json.dumps(second_context, ensure_ascii=False)}")
    print(f"extract_status={extracted.status_code}")
    print(f"extract_json={json.dumps(extracted.json(), ensure_ascii=False)}")


if __name__ == "__main__":
    main()

