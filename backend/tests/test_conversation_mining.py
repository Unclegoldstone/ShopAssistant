from __future__ import annotations

import os
from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from app.config import Settings
from app.db.session import create_database_runtime
from app.models import (
    Conversation,
    ConversationStatus,
    KnowledgeMiningRun,
    KnowledgeMiningRunStatus,
    KnowledgeStaging,
    Message,
    MessageRole,
)
from app.services.conversation_mining import (
    ConversationMiningService,
    ExtractedKnowledge,
    ExtractedKnowledgeBatch,
    MiningMessage,
    assemble_visible_turns,
    select_turns_within_budget,
)


def message(
    message_id: int,
    role: MessageRole,
    content: str,
    *,
    conversation_id: str = "c1",
    status: ConversationStatus = ConversationStatus.ACTIVE,
    tool_calls: list[dict[str, object]] | None = None,
    tool_call_id: str | None = None,
) -> MiningMessage:
    return MiningMessage(
        id=message_id,
        conversation_id=conversation_id,
        conversation_status=status,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        created_at=datetime(2026, 10, 2),
    )


def test_visible_turns_exclude_failed_tool_payload_and_tool_call_assistant() -> None:
    messages = [
        message(1, MessageRole.USER, "订单怎么退"),
        message(2, MessageRole.ASSISTANT, "", tool_calls=[{"name": "query_order"}]),
        message(3, MessageRole.TOOL, '{"private":"payload"}', tool_call_id="call-1"),
        message(4, MessageRole.ASSISTANT, "可以在订单页申请退货。"),
        message(
            5,
            MessageRole.USER,
            "失败会话问题",
            conversation_id="failed",
            status=ConversationStatus.FAILED,
        ),
        message(
            6,
            MessageRole.ASSISTANT,
            "失败会话回答",
            conversation_id="failed",
            status=ConversationStatus.FAILED,
        ),
    ]

    turns = assemble_visible_turns(messages)

    assert len(turns) == 1
    assert turns[0].first_message_id == 1
    assert turns[0].last_message_id == 4
    assert turns[0].user_content == "订单怎么退"
    assert turns[0].assistant_content == "可以在订单页申请退货。"
    assert "payload" not in turns[0].assistant_content


def test_budget_keeps_complete_turns_and_always_allows_first_turn() -> None:
    turns = assemble_visible_turns(
        [
            message(1, MessageRole.USER, "第一问"),
            message(2, MessageRole.ASSISTANT, "第一答"),
            message(3, MessageRole.USER, "第二问"),
            message(4, MessageRole.ASSISTANT, "第二答"),
        ]
    )

    selected = select_turns_within_budget(turns, token_budget=5, token_counter=len)
    oversized = select_turns_within_budget(turns, token_budget=1, token_counter=len)

    assert [turn.last_message_id for turn in selected] == [2]
    assert [turn.last_message_id for turn in oversized] == [2]


def test_extracted_knowledge_requires_non_empty_questions() -> None:
    with pytest.raises(ValidationError):
        ExtractedKnowledge(
            category="售后",
            questions=[],
            answer="回答",
            is_critical=False,
            should_store=True,
            reason="可复用",
        )


class FakeStructuredRunnable:
    async def ainvoke(self, messages: object) -> ExtractedKnowledgeBatch:
        return ExtractedKnowledgeBatch(
            items=[
                ExtractedKnowledge(
                    turn_index=0,
                    category="售后",
                    questions=["商品损坏怎么办"],
                    answer="请保留包装并提供破损照片。",
                    is_critical=False,
                    should_store=True,
                    reason="可复用售后流程",
                )
            ]
        )


class FakeChatModel:
    def with_structured_output(self, schema: object, **kwargs: object) -> FakeStructuredRunnable:
        return FakeStructuredRunnable()


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="需要真实 MySQL",
)
@pytest.mark.asyncio
async def test_mining_persists_staging_then_advances_completed_cursor() -> None:
    runtime = create_database_runtime(Settings())
    conversation_id = f"test-mining-{uuid4().hex}"
    marker_batch = f"test-marker-{uuid4().hex}"
    try:
        async with runtime.session_factory.begin() as session:
            old_cursor = await session.scalar(select(func.max(Message.id)))
            session.add(
                KnowledgeMiningRun(
                    batch_id=marker_batch,
                    status=KnowledgeMiningRunStatus.COMPLETED,
                    cursor_end_message_id=old_cursor,
                )
            )
            session.add(
                Conversation(
                    id=conversation_id,
                    user_id="test-user",
                    status=ConversationStatus.ACTIVE,
                )
            )
            await session.flush()
            session.add_all(
                [
                    Message(
                        conversation_id=conversation_id,
                        role=MessageRole.USER,
                        content="商品损坏怎么办",
                    ),
                    Message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content="请保留包装并提供破损照片。",
                    ),
                ]
            )

        service = ConversationMiningService(
            session_factory=runtime.session_factory,
            model=FakeChatModel(),
            batch_size=5,
            token_budget=1000,
        )
        result = await service.run_once()

        assert result.processed_turns == 1
        assert result.stored == 1
        async with runtime.session_factory() as session:
            staging = await session.scalar(
                select(KnowledgeStaging).where(
                    KnowledgeStaging.conversation_id == conversation_id
                )
            )
            run = await session.scalar(
                select(KnowledgeMiningRun).where(KnowledgeMiningRun.batch_id == result.batch_id)
            )
            assert staging is not None
            assert staging.questions == ["商品损坏怎么办"]
            assert run is not None
            assert run.status is KnowledgeMiningRunStatus.COMPLETED
            assert run.cursor_end_message_id == result.cursor_end_message_id
    finally:
        async with runtime.session_factory.begin() as session:
            await session.execute(
                delete(KnowledgeStaging).where(
                    KnowledgeStaging.conversation_id == conversation_id
                )
            )
            await session.execute(
                delete(KnowledgeMiningRun).where(
                    KnowledgeMiningRun.batch_id.in_([marker_batch, result.batch_id])
                    if "result" in locals()
                    else KnowledgeMiningRun.batch_id == marker_batch
                )
            )
            await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
        await runtime.dispose()
