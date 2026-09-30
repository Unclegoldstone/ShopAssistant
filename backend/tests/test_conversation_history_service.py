from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.session import create_database_runtime
from app.models import Message, MessageRole
from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository
from app.services.conversation_history import (
    ConversationHistoryNotFoundError,
    ConversationHistoryService,
    records_to_history_messages,
)


def message(
    message_id: int,
    role: MessageRole,
    content: str,
    *,
    tool_calls: list[dict[str, object]] | None = None,
    tool_call_id: str | None = None,
) -> Message:
    return Message(
        id=message_id,
        conversation_id="web-history-test",
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )


def test_records_to_history_messages_keeps_visible_chat() -> None:
    records = [
        message(1, MessageRole.USER, "你好"),
        message(2, MessageRole.ASSISTANT, "您好，请问有什么可以帮您？"),
    ]

    result = records_to_history_messages(records)

    assert [item.model_dump() for item in result] == [
        {"role": "user", "content": "你好", "tool_name": None},
        {
            "role": "assistant",
            "content": "您好，请问有什么可以帮您？",
            "tool_name": None,
        },
    ]


def test_records_to_history_messages_hides_tool_payload_and_restores_tool_name() -> None:
    records = [
        message(1, MessageRole.USER, "订单 1001 的物流到哪了"),
        message(
            2,
            MessageRole.ASSISTANT,
            "",
            tool_calls=[
                {
                    "id": "call-logistics",
                    "name": "query_logistics",
                    "args": {"order_id": "1001"},
                }
            ],
        ),
        message(
            3,
            MessageRole.TOOL,
            '{"tracking_no":"SECRET-INTERNAL"}',
            tool_call_id="call-logistics",
        ),
        message(4, MessageRole.ASSISTANT, "订单正在运输中。"),
        message(5, MessageRole.USER, "谢谢"),
        message(6, MessageRole.ASSISTANT, "不客气。"),
    ]

    result = records_to_history_messages(records)

    assert [item.model_dump() for item in result] == [
        {
            "role": "user",
            "content": "订单 1001 的物流到哪了",
            "tool_name": None,
        },
        {
            "role": "assistant",
            "content": "订单正在运输中。",
            "tool_name": "query_logistics",
        },
        {"role": "user", "content": "谢谢", "tool_name": None},
        {"role": "assistant", "content": "不客气。", "tool_name": None},
    ]
    assert "SECRET-INTERNAL" not in str(result)


def test_records_to_history_messages_does_not_invent_missing_assistant_reply() -> None:
    records = [
        message(1, MessageRole.USER, "查物流"),
        message(
            2,
            MessageRole.ASSISTANT,
            "",
            tool_calls=[{"id": "call-1", "name": "query_logistics", "args": {}}],
        ),
        message(3, MessageRole.TOOL, "内部结果", tool_call_id="call-1"),
        message(4, MessageRole.USER, "下一轮"),
        message(5, MessageRole.ASSISTANT, "下一轮回答"),
    ]

    result = records_to_history_messages(records)

    assert [item.model_dump() for item in result] == [
        {"role": "user", "content": "查物流", "tool_name": None},
        {"role": "user", "content": "下一轮", "tool_name": None},
        {"role": "assistant", "content": "下一轮回答", "tool_name": None},
    ]


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="set SHOP_ASSISTANT_RUN_MYSQL_TESTS=1 to run MySQL integration tests",
)
@pytest.mark.asyncio
async def test_history_service_isolates_users_and_hides_internal_messages() -> None:
    runtime = create_database_runtime(Settings())
    suffix = uuid4().hex
    demo_conversation_id = f"history-demo-{suffix}"
    user1_conversation_id = f"history-user1-{suffix}"
    service = ConversationHistoryService(runtime.session_factory)

    try:
        async with runtime.session_factory.begin() as session:
            conversations = ConversationRepository(session)
            messages = MessageRepository(session)
            await conversations.get_or_create(demo_conversation_id, "demo-user")
            await messages.add(
                demo_conversation_id,
                MessageRole.USER,
                "demo-user 的问题",
            )
            await messages.add(
                demo_conversation_id,
                MessageRole.ASSISTANT,
                "demo-user 的回答",
            )
            await conversations.get_or_create(user1_conversation_id, "user1")
            await messages.add(user1_conversation_id, MessageRole.USER, "user1 的问题")
            await messages.add(
                user1_conversation_id,
                MessageRole.ASSISTANT,
                "",
                tool_calls=[{"id": "call-1", "name": "query_faq", "args": {}}],
            )
            await messages.add(
                user1_conversation_id,
                MessageRole.TOOL,
                "内部 FAQ 结果",
                tool_call_id="call-1",
            )
            await messages.add(
                user1_conversation_id,
                MessageRole.ASSISTANT,
                "user1 的回答",
            )

        demo_list = await service.list_conversations("demo-user")
        user1_list = await service.list_conversations("user1")
        demo_item = next(item for item in demo_list if item.id == demo_conversation_id)
        user1_item = next(item for item in user1_list if item.id == user1_conversation_id)

        assert all(item.id != user1_conversation_id for item in demo_list)
        assert all(item.id != demo_conversation_id for item in user1_list)
        assert demo_item.preview == "demo-user 的问题"
        assert demo_item.message_count == 2
        assert user1_item.message_count == 2

        with pytest.raises(ConversationHistoryNotFoundError):
            await service.get_history(user1_conversation_id, "demo-user")

        history = await service.get_history(user1_conversation_id, "user1")
        assert [item.model_dump() for item in history.messages] == [
            {"role": "user", "content": "user1 的问题", "tool_name": None},
            {
                "role": "assistant",
                "content": "user1 的回答",
                "tool_name": "query_faq",
            },
        ]
    finally:
        async with runtime.session_factory.begin() as session:
            repository = ConversationRepository(session)
            await repository.delete(demo_conversation_id)
            await repository.delete(user1_conversation_id)
        await runtime.dispose()
