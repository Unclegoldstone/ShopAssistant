from __future__ import annotations

import os
import random
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.session import create_database_runtime
from app.models import ConversationStatus
from app.repositories.conversations import ConversationRepository
from app.tools.business import build_business_tools
from app.tools.executor import ToolExecutionContext, ToolExecutor
from app.tools.registry import ToolRegistry


def test_business_tools_have_fixed_names_and_strict_schemas() -> None:
    tools = build_business_tools(None, rng=random.Random(7))

    assert [tool.name for tool in tools] == [
        "query_order",
        "query_product",
        "query_logistics",
        "query_faq",
        "create_ticket",
    ]
    for business_tool in tools:
        assert business_tool.description
        assert business_tool.args_schema is not None
        assert business_tool.args_schema.model_json_schema()["additionalProperties"] is False


@pytest.mark.asyncio
async def test_demo_query_tools_return_requested_identifiers() -> None:
    tools = ToolRegistry(build_business_tools(None, rng=random.Random(7)))

    order = await tools.get("query_order").ainvoke({"order_id": "1001"})
    product = await tools.get("query_product").ainvoke({"keyword": "像素帽"})
    logistics = await tools.get("query_logistics").ainvoke({"order_id": "1001"})

    assert order["order_id"] == "1001"
    assert product["keyword"] == "像素帽"
    assert logistics["order_id"] == "1001"


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the migrated Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_database_tools_find_faq_and_create_one_ticket() -> None:
    runtime = create_database_runtime(Settings())
    conversation_id = f"tool-test-{uuid4().hex}"
    registry = ToolRegistry(build_business_tools(runtime.session_factory, rng=random.Random(7)))
    executor = ToolExecutor(registry, timeout_seconds=2, max_attempts=2)
    context = ToolExecutionContext(
        conversation_id=conversation_id,
        user_id="demo-user",
        tool_call_id="call-ticket-1",
    )

    try:
        faq_result = await executor.execute(
            {"name": "query_faq", "args": {"keyword": "退货政策"}, "id": "call-faq-1"},
            context=context,
        )
        missing_result = await executor.execute(
            {"name": "query_faq", "args": {"keyword": "邮费"}, "id": "call-faq-2"},
            context=context,
        )
        first_ticket = await executor.execute(
            {
                "name": "create_ticket",
                "args": {"issue_description": "商品破损", "ticket_type": "售后"},
                "id": "call-ticket-1",
            },
            context=context,
        )
        second_ticket = await executor.execute(
            {
                "name": "create_ticket",
                "args": {"issue_description": "商品破损", "ticket_type": "售后"},
                "id": "call-ticket-1",
            },
            context=context,
        )

        async with runtime.session_factory() as session:
            conversation = await ConversationRepository(session).get(conversation_id)

        assert '"ok": true' in faq_result.content
        assert "退货政策是什么" in faq_result.content
        assert '"code": "not_found"' in missing_result.content
        assert first_ticket.content == second_ticket.content
        assert conversation is not None
        assert conversation.status is ConversationStatus.WAITING_HUMAN
    finally:
        async with runtime.session_factory.begin() as session:
            await ConversationRepository(session).delete(conversation_id)
        await runtime.dispose()
