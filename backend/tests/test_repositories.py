from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.session import create_database_runtime
from app.models import ConversationStatus, MessageRole
from app.repositories.conversations import ConversationRepository
from app.repositories.faq import FaqRepository
from app.repositories.messages import MessageRepository
from app.repositories.tickets import TicketRepository


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the migrated Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_repositories_persist_history_query_faq_and_create_ticket_idempotently() -> None:
    runtime = create_database_runtime(Settings())
    conversation_id = f"repo-test-{uuid4().hex}"

    try:
        async with runtime.session_factory.begin() as session:
            conversations = ConversationRepository(session)
            messages = MessageRepository(session)
            tickets = TicketRepository(session)

            conversation = await conversations.get_or_create(conversation_id, "demo-user")
            await messages.add(conversation.id, MessageRole.USER, "我要退货")
            await messages.add(conversation.id, MessageRole.ASSISTANT, "请提供订单号")
            first_ticket = await tickets.create_or_get(
                conversation_id=conversation.id,
                tool_call_id="call-stable-1",
                issue_description="商品破损，需要人工处理",
                ticket_type="售后",
            )
            second_ticket = await tickets.create_or_get(
                conversation_id=conversation.id,
                tool_call_id="call-stable-1",
                issue_description="不会重复创建",
                ticket_type="其他",
            )
            await conversations.set_status(conversation.id, ConversationStatus.WAITING_HUMAN)

        async with runtime.session_factory() as session:
            conversations = ConversationRepository(session)
            messages = MessageRepository(session)
            faq = FaqRepository(session)

            stored_conversation = await conversations.get(conversation_id)
            stored_messages = await messages.list_for_conversation(conversation_id)
            return_policy = await faq.search_by_question("退货政策")
            shipping = await faq.search_by_question("邮费")

        assert stored_conversation is not None
        assert stored_conversation.status is ConversationStatus.WAITING_HUMAN
        assert [item.content for item in stored_messages] == ["我要退货", "请提供订单号"]
        assert first_ticket.ticket_no == second_ticket.ticket_no
        assert second_ticket.issue_description == "商品破损，需要人工处理"
        assert [item.question for item in return_policy] == ["退货政策是什么"]
        assert shipping == []
    finally:
        async with runtime.session_factory.begin() as session:
            await ConversationRepository(session).delete(conversation_id)
        await runtime.dispose()
