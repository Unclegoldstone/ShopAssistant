from __future__ import annotations

import json
import os
import random
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from app.config import Settings
from app.conversation_store import ConversationStore
from app.db.session import create_database_runtime
from app.services.chat import ChatService
from app.tools.business import build_business_tools
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from tests.fakes import FakeStreamingModel


@tool
async def lookup_demo(value: str) -> dict[str, str]:
    """Look up one deterministic demo value."""
    return {"value": value, "status": "found"}


def build_service(
    model: FakeStreamingModel,
    store: ConversationStore,
) -> ChatService:
    registry = ToolRegistry([lookup_demo])
    return ChatService(
        model,
        store,
        registry=registry,
        tool_executor=ToolExecutor(registry, timeout_seconds=1, max_attempts=2),
        model_name="qwen-test",
        history_max_tokens=500,
    )


@pytest.mark.asyncio
async def test_one_tool_is_executed_persisted_and_used_for_final_stream() -> None:
    decision = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "lookup_demo",
                "args": {"value": "1001"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    model = FakeStreamingModel([["查询", "完成"]], decision_responses=[decision])
    store = ConversationStore()
    service = build_service(model, store)

    prepared = await service.prepare_turn("c-tool", "查一下 1001", user_id="demo-user")
    events = [event async for event in service.stream_prepared(prepared)]
    history = await store.get_history("c-tool")

    assert prepared.tool_name == "lookup_demo"
    assert events[-1] == "data: [DONE]\n\n"
    assert [type(message) for message in history] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
    ]
    assert history[1].tool_calls[0]["id"] == "call-1"
    assert json.loads(history[2].content)["data"]["value"] == "1001"
    assert history[3].content == "查询完成"
    assert isinstance(model.calls[0][-1], ToolMessage)


@pytest.mark.asyncio
async def test_no_tool_still_uses_final_stream_and_persists_turn() -> None:
    model = FakeStreamingModel([["你好"]], decision_responses=[AIMessage(content="无需工具")])
    store = ConversationStore()
    service = build_service(model, store)

    prepared = await service.prepare_turn("c-plain", "你好", user_id="demo-user")
    _ = [event async for event in service.stream_prepared(prepared)]

    assert prepared.tool_name is None
    assert await store.get_history("c-plain") == [
        HumanMessage(content="你好"),
        AIMessage(content="你好"),
    ]


@pytest.mark.asyncio
async def test_multiple_tool_calls_are_capped_at_the_first_call() -> None:
    decision = AIMessage(
        content="",
        tool_calls=[
            {"name": "lookup_demo", "args": {"value": "first"}, "id": "call-1"},
            {"name": "lookup_demo", "args": {"value": "second"}, "id": "call-2"},
        ],
    )
    model = FakeStreamingModel([["只处理一个"]], decision_responses=[decision])
    store = ConversationStore()
    service = build_service(model, store)

    prepared = await service.prepare_turn("c-multi", "查询", user_id="demo-user")
    _ = [event async for event in service.stream_prepared(prepared)]
    history = await store.get_history("c-multi")

    assert len(history) == 4
    assert history[1].tool_calls == [decision.tool_calls[0]]
    assert json.loads(history[2].content)["data"]["value"] == "first"


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_to_model_but_not_exposed_as_header() -> None:
    decision = AIMessage(
        content="",
        tool_calls=[{"name": "不存在的工具", "args": {}, "id": "call-unknown"}],
    )
    model = FakeStreamingModel([["该工具不可用"]], decision_responses=[decision])
    store = ConversationStore()
    service = build_service(model, store)

    prepared = await service.prepare_turn("c-unknown", "查询", user_id="demo-user")
    _ = [event async for event in service.stream_prepared(prepared)]
    history = await store.get_history("c-unknown")

    assert prepared.tool_name is None
    assert json.loads(history[2].content)["error"]["code"] == "unknown_tool"


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the migrated Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_tool_chat_chain_survives_database_store_recreation() -> None:
    runtime = create_database_runtime(Settings())
    conversation_id = f"chat-flow-test-{uuid4().hex}"
    decision = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "query_faq",
                "args": {"keyword": "退货政策"},
                "id": "call-faq-db-1",
                "type": "tool_call",
            }
        ],
    )
    model = FakeStreamingModel([["支持七天内申请退货。"]], decision_responses=[decision])
    registry = ToolRegistry(build_business_tools(runtime.session_factory, rng=random.Random(7)))
    store = ConversationStore(runtime.session_factory)
    service = ChatService(
        model,
        store,
        registry=registry,
        tool_executor=ToolExecutor(registry, timeout_seconds=2, max_attempts=2),
        model_name="qwen-test",
        history_max_tokens=500,
    )

    try:
        prepared = await service.prepare_turn(
            conversation_id,
            "退货政策是什么",
            user_id="demo-user",
        )
        _ = [event async for event in service.stream_prepared(prepared)]
        history = await ConversationStore(runtime.session_factory).get_history(conversation_id)

        assert prepared.tool_name == "query_faq"
        assert [type(message) for message in history] == [
            HumanMessage,
            AIMessage,
            ToolMessage,
            AIMessage,
        ]
        assert "退货政策是什么" in history[2].content
    finally:
        await store.clear(conversation_id)
        await runtime.dispose()
