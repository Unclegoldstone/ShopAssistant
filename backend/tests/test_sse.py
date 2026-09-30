from __future__ import annotations

import json

from app.sse import done_event, error_event, openai_chunk_event


def event_payload(event: str) -> dict:
    assert event.startswith("data: ")
    return json.loads(event.removeprefix("data: ").strip())


def test_openai_chunk_event_has_chat_completion_shape_and_readable_chinese() -> None:
    event = openai_chunk_event(
        completion_id="chatcmpl-1",
        created=123,
        model="qwen-test",
        delta={"content": "您好"},
    )
    payload = event_payload(event)

    assert payload["object"] == "chat.completion.chunk"
    assert payload["choices"][0]["delta"] == {"content": "您好"}
    assert payload["choices"][0]["finish_reason"] is None
    assert "您好" in event
    assert "\\u" not in event


def test_error_and_done_events_are_well_formed() -> None:
    error = event_payload(error_event())

    assert error == {
        "error": {
            "message": "上游模型服务暂时不可用，请稍后重试",
            "type": "upstream_error",
            "code": "model_stream_error",
        }
    }
    assert done_event() == "data: [DONE]\n\n"
