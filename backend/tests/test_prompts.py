from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.prompts import (
    CUSTOMER_SERVICE_SYSTEM_PROMPT,
    chat_prompt,
    extraction_prompt,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_chat_prompt_contains_system_history_and_current_user_message() -> None:
    messages = chat_prompt.format_messages(history=[], user_input="你好")

    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == CUSTOMER_SERVICE_SYSTEM_PROMPT
    assert isinstance(messages[-1], HumanMessage)
    assert messages[-1].content == "你好"


def test_system_prompt_contains_required_boundaries() -> None:
    required_phrases = (
        "电商平台智能客服",
        "不得编造",
        "不得声称已经执行",
        "不得泄露",
        "必须优先依据工具结果",
        "每轮最多选择一个",
    )

    assert all(phrase in CUSTOMER_SERVICE_SYSTEM_PROMPT for phrase in required_phrases)


def test_system_prompts_are_loaded_from_external_files() -> None:
    customer_service_file = BACKEND_ROOT / "prompts" / "customer_service_system.txt"
    extraction_file = BACKEND_ROOT / "prompts" / "after_sales_extraction_system.txt"

    assert (
        CUSTOMER_SERVICE_SYSTEM_PROMPT == customer_service_file.read_text(encoding="utf-8").strip()
    )
    assert extraction_prompt.format_messages(description="测试")[0].content == (
        extraction_file.read_text(encoding="utf-8").strip()
    )


def test_extraction_prompt_includes_input_and_missing_value_rule() -> None:
    messages = extraction_prompt.format_messages(description="订单 A1 想退款")

    assert "订单 A1 想退款" in messages[-1].content
    assert "null" in messages[0].content
