from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.config import Settings
from app.conversation_store import ConversationStore, InputTooLongError
from app.db.session import create_database_runtime
from app.models import MessageRole


@pytest.mark.asyncio
async def test_conversations_are_isolated_and_return_copies() -> None:
    store = ConversationStore()
    await store.commit_turn("a", "问题 A", "回答 A")
    await store.commit_turn("b", "问题 B", "回答 B")

    history_a = await store.get_history("a")
    history_b = await store.get_history("b")
    history_a.append(HumanMessage(content="本地修改"))

    assert [message.content for message in history_a[:2]] == ["问题 A", "回答 A"]
    assert [message.content for message in history_b] == ["问题 B", "回答 B"]
    assert len(await store.get_history("a")) == 2


@pytest.mark.asyncio
async def test_clear_removes_only_selected_conversation() -> None:
    store = ConversationStore()
    await store.commit_turn("a", "问题 A", "回答 A")
    await store.commit_turn("b", "问题 B", "回答 B")

    await store.clear("a")

    assert await store.get_history("a") == []
    assert len(await store.get_history("b")) == 2


@pytest.mark.asyncio
async def test_trim_keeps_recent_complete_turns() -> None:
    store = ConversationStore()
    await store.commit_turn("a", "最早问题 " * 20, "最早回答 " * 20)
    await store.commit_turn("a", "最近问题", "最近回答")

    trimmed = await store.history_for_request("a", "当前问题", max_tokens=30)

    assert trimmed == [HumanMessage(content="最近问题"), AIMessage(content="最近回答")]


@pytest.mark.asyncio
async def test_current_message_over_budget_is_rejected() -> None:
    store = ConversationStore()

    with pytest.raises(InputTooLongError):
        await store.history_for_request("a", "这是一个明显超过极小预算的当前问题", max_tokens=2)


@pytest.mark.asyncio
async def test_same_conversation_lock_serializes_requests() -> None:
    store = ConversationStore()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        async with store.lock("same"):
            order.append("first-enter")
            first_entered.set()
            await release_first.wait()
            order.append("first-exit")

    async def second() -> None:
        await first_entered.wait()
        async with store.lock("same"):
            order.append("second-enter")

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)

    assert order == ["first-enter"]
    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert order == ["first-enter", "first-exit", "second-enter"]


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the migrated Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_database_history_survives_store_recreation_with_complete_tool_chain() -> None:
    runtime = create_database_runtime(Settings())
    conversation_id = f"store-test-{uuid4().hex}"
    tool_calls = [
        {
            "name": "query_faq",
            "args": {"keyword": "退货政策"},
            "id": "call-1",
            "type": "tool_call",
        }
    ]

    try:
        first_store = ConversationStore(runtime.session_factory)
        await first_store.append_message(
            conversation_id,
            user_id="demo-user",
            role=MessageRole.USER,
            content="退货政策是什么",
        )
        await first_store.append_message(
            conversation_id,
            user_id="demo-user",
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=tool_calls,
        )
        await first_store.append_message(
            conversation_id,
            user_id="demo-user",
            role=MessageRole.TOOL,
            content='{"status":"ok"}',
            tool_call_id="call-1",
        )
        await first_store.append_message(
            conversation_id,
            user_id="demo-user",
            role=MessageRole.ASSISTANT,
            content="支持七天内申请退货。",
        )

        recreated_store = ConversationStore(runtime.session_factory)
        history = await recreated_store.get_history(conversation_id)
        trimmed = await recreated_store.history_for_request(
            conversation_id,
            "我需要准备什么？",
            max_tokens=500,
        )

        assert [type(message) for message in history] == [
            HumanMessage,
            AIMessage,
            ToolMessage,
            AIMessage,
        ]
        assert history[1].tool_calls == tool_calls
        assert history[2].tool_call_id == "call-1"
        assert trimmed == history
    finally:
        await ConversationStore(runtime.session_factory).clear(conversation_id)
        await runtime.dispose()
