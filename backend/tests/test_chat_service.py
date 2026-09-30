from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.conversation_store import ConversationStore
from app.services.chat import ChatService
from tests.fakes import FakeStreamingModel


def parse_data(event: str) -> dict | str:
    payload = event.removeprefix("data: ").strip()
    return payload if payload == "[DONE]" else json.loads(payload)


@pytest.mark.asyncio
async def test_chat_stream_emits_role_each_chunk_stop_and_done() -> None:
    model = FakeStreamingModel([["您", "好"]])
    store = ConversationStore()
    service = ChatService(model, store, model_name="qwen-test", history_max_tokens=100)

    events = [event async for event in service.stream("c1", "你好")]
    payloads = [parse_data(event) for event in events]

    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    content_chunks = [
        payloads[1]["choices"][0]["delta"]["content"],
        payloads[2]["choices"][0]["delta"]["content"],
    ]
    assert content_chunks == ["您", "好"]
    assert payloads[3]["choices"][0]["finish_reason"] == "stop"
    assert payloads[4] == "[DONE]"


@pytest.mark.asyncio
async def test_successful_stream_commits_complete_turn() -> None:
    model = FakeStreamingModel([["完整", "回答"]])
    store = ConversationStore()
    service = ChatService(model, store, model_name="qwen-test", history_max_tokens=100)

    _ = [event async for event in service.stream("c1", "问题")]

    assert await store.get_history("c1") == [
        HumanMessage(content="问题"),
        AIMessage(content="完整回答"),
    ]


@pytest.mark.asyncio
async def test_second_turn_receives_first_turn_as_context() -> None:
    model = FakeStreamingModel([["第一答"], ["第二答"]])
    store = ConversationStore()
    service = ChatService(model, store, model_name="qwen-test", history_max_tokens=200)

    _ = [event async for event in service.stream("same", "第一问")]
    _ = [event async for event in service.stream("same", "第二问")]

    second_call = model.calls[1]
    assert isinstance(second_call[0], SystemMessage)
    assert [message.content for message in second_call[1:]] == [
        "第一问",
        "第一答",
        "第二问",
    ]


@pytest.mark.asyncio
async def test_failed_stream_emits_safe_error_and_keeps_user_audit_message() -> None:
    model = FakeStreamingModel([RuntimeError("secret upstream detail")])
    store = ConversationStore()
    service = ChatService(model, store, model_name="qwen-test", history_max_tokens=100)

    events = [event async for event in service.stream("c1", "问题")]

    assert "secret upstream detail" not in "".join(events)
    assert parse_data(events[-2])["error"]["code"] == "model_stream_error"
    assert parse_data(events[-1]) == "[DONE]"
    assert await store.get_history("c1") == [HumanMessage(content="问题")]
