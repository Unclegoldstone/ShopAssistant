from __future__ import annotations

import json
from typing import Any


def _data_event(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"data: {serialized}\n\n"


def openai_chunk_event(
    *,
    completion_id: str,
    created: int,
    model: str,
    delta: dict[str, str],
    finish_reason: str | None = None,
) -> str:
    return _data_event(
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }
    )


def error_event() -> str:
    return _data_event(
        {
            "error": {
                "message": "上游模型服务暂时不可用，请稍后重试",
                "type": "upstream_error",
                "code": "model_stream_error",
            }
        }
    )


def done_event() -> str:
    return "data: [DONE]\n\n"
