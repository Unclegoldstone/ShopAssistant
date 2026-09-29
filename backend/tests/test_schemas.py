from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import AfterSalesInfo, AfterSalesRequest, ChatCompletionRequest


def valid_chat_payload() -> dict:
    return {
        "model": "qwen-test",
        "conversation_id": "customer-001",
        "messages": [{"role": "user", "content": "我的耳机没有声音"}],
        "stream": True,
    }


def test_chat_request_accepts_one_user_message() -> None:
    request = ChatCompletionRequest.model_validate(valid_chat_payload())

    assert request.messages[0].content == "我的耳机没有声音"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("messages", []),
        ("messages", [{"role": "assistant", "content": "不可用"}]),
        ("messages", [{"role": "user", "content": "   "}]),
        ("stream", False),
        ("conversation_id", "bad id with spaces"),
        ("model", ""),
    ],
)
def test_chat_request_rejects_invalid_input(field: str, value: object) -> None:
    payload = valid_chat_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate(payload)


def test_after_sales_fields_are_fixed_and_nullable() -> None:
    result = AfterSalesInfo(
        order_id=None,
        request_type=None,
        expected_solution=None,
    )

    assert result.model_dump() == {
        "order_id": None,
        "request_type": None,
        "expected_solution": None,
    }
    assert set(AfterSalesInfo.model_json_schema()["required"]) == {
        "order_id",
        "request_type",
        "expected_solution",
    }


def test_after_sales_request_rejects_blank_text() -> None:
    with pytest.raises(ValidationError):
        AfterSalesRequest(text="  ")
