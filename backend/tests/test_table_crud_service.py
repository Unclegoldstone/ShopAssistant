from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.config import Settings
from app.db.session import create_database_runtime
from app.models import Conversation, Faq, KnowledgeChunk, KnowledgeVectorStatus
from app.repositories.knowledge import KnowledgeRepository
from app.schemas import TableRecordWrite
from app.services.table_crud import (
    TableCrudService,
    TableRecordReadOnlyError,
    _can_update,
    _is_test_record,
)


def test_business_update_permission_is_limited_to_faq() -> None:
    faq = Faq(question="条款", answer="内容", category="政策", is_test=False)
    conversation = Conversation(id="business-conversation", user_id="demo-user")

    assert _can_update(faq) is True
    assert _is_test_record(faq) is False
    assert _can_update(conversation) is False
    assert _is_test_record(conversation) is False


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="set SHOP_ASSISTANT_RUN_MYSQL_TESTS=1 to run MySQL integration tests",
)
@pytest.mark.asyncio
async def test_table_crud_service_covers_all_four_tables() -> None:
    runtime = create_database_runtime(Settings())
    service = TableCrudService(runtime.session_factory)
    suffix = uuid4().hex[:12]
    conversation_id = f"test-lab-{suffix}"
    ticket_no = f"TL-{suffix}"
    created: list[tuple[str, str]] = []

    try:
        protected_faq = next(
            item for item in await service.list_records("faq") if not item.editable
        )
        assert protected_faq.can_update is True
        assert protected_faq.can_delete is False
        original_faq = dict(protected_faq.values)
        updated_business_faq = await service.update(
            "faq",
            protected_faq.key,
            TableRecordWrite(
                values={
                    "question": original_faq["question"],
                    "answer": f"{original_faq['answer']}（更新测试）",
                    "category": original_faq["category"],
                }
            ),
        )
        assert updated_business_faq.values["answer"].endswith("（更新测试）")
        await service.update(
            "faq",
            protected_faq.key,
            TableRecordWrite(
                values={
                    "question": original_faq["question"],
                    "answer": original_faq["answer"],
                    "category": original_faq["category"],
                }
            ),
        )
        with pytest.raises(TableRecordReadOnlyError):
            await service.delete("faq", protected_faq.key)

        conversation = await service.create(
            "conversations",
            TableRecordWrite(
                values={"id": conversation_id, "user_id": "demo-user", "status": "active"}
            ),
        )
        created.append(("conversations", conversation.key))
        assert conversation.values["status"] == "active"

        faq = await service.create(
            "faq",
            TableRecordWrite(
                values={
                    "question": f"测试问题-{suffix}",
                    "answer": "创建",
                    "category": "自定义分类",
                }
            ),
        )
        created.append(("faq", faq.key))
        async with runtime.session_factory() as session:
            knowledge = await KnowledgeRepository(session).get_by_source_key(f"faq:{faq.key}")
            assert knowledge is not None
            assert knowledge.vector_status is KnowledgeVectorStatus.PENDING

        message = await service.create(
            "messages",
            TableRecordWrite(
                values={
                    "conversation_id": conversation_id,
                    "role": "user",
                    "content": "创建消息",
                    "tool_calls": None,
                    "tool_call_id": None,
                }
            ),
        )
        created.append(("messages", message.key))

        ticket = await service.create(
            "tickets",
            TableRecordWrite(
                values={
                    "ticket_no": ticket_no,
                    "conversation_id": conversation_id,
                    "issue_description": "创建工单",
                    "ticket_type": "测试",
                    "status": "open",
                }
            ),
        )
        created.append(("tickets", ticket.key))

        for table_name in ("faq", "conversations", "messages", "tickets"):
            assert await service.list_records(table_name)

        updated_faq = await service.update(
            "faq",
            faq.key,
            TableRecordWrite(
                values={
                    "question": f"测试问题-{suffix}",
                    "answer": "更新",
                    "category": "更新后的分类",
                }
            ),
        )
        assert updated_faq.values["answer"] == "更新"
        assert updated_faq.values["category"] == "更新后的分类"
        async with runtime.session_factory() as session:
            knowledge = await KnowledgeRepository(session).get_by_source_key(f"faq:{faq.key}")
            assert knowledge is not None
            assert knowledge.answer == "更新"

        updated_conversation = await service.update(
            "conversations",
            conversation.key,
            TableRecordWrite(values={"user_id": "demo-user", "status": "closed"}),
        )
        assert updated_conversation.values["status"] == "closed"

        updated_message = await service.update(
            "messages",
            message.key,
            TableRecordWrite(
                values={
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": "更新消息",
                    "tool_calls": None,
                    "tool_call_id": None,
                }
            ),
        )
        assert updated_message.values["role"] == "assistant"

        updated_ticket = await service.update(
            "tickets",
            ticket.key,
            TableRecordWrite(
                values={
                    "conversation_id": conversation_id,
                    "issue_description": "更新工单",
                    "ticket_type": "测试",
                    "status": "resolved",
                }
            ),
        )
        assert updated_ticket.values["status"] == "resolved"

        await service.delete("faq", faq.key)
        created.remove(("faq", faq.key))
        async with runtime.session_factory() as session:
            knowledge = await KnowledgeRepository(session).get_by_source_key(f"faq:{faq.key}")
            assert knowledge is not None
            assert knowledge.vector_status is KnowledgeVectorStatus.PENDING_DELETE
    finally:
        for table_name, key in reversed(created):
            try:
                await service.delete(table_name, key)
            except Exception:
                pass
        if "faq" in locals():
            async with runtime.session_factory.begin() as session:
                await session.execute(
                    delete(KnowledgeChunk).where(
                        KnowledgeChunk.source_key == f"faq:{faq.key}"
                    )
                )
        await runtime.dispose()
