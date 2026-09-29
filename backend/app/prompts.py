from __future__ import annotations

from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

PROMPT_DIRECTORY = Path(__file__).resolve().parents[1] / "prompts"


def _load_prompt(filename: str) -> str:
    prompt = (PROMPT_DIRECTORY / filename).read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Prompt file must not be empty: {filename}")
    return prompt


CUSTOMER_SERVICE_SYSTEM_PROMPT = _load_prompt("customer_service_system.txt")
EXTRACTION_SYSTEM_PROMPT = _load_prompt("after_sales_extraction_system.txt")

chat_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", CUSTOMER_SERVICE_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{user_input}"),
    ]
)

extraction_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", EXTRACTION_SYSTEM_PROMPT),
        ("human", "请抽取以下售后描述：\n{description}"),
    ]
)
