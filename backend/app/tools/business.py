from __future__ import annotations

import random
from datetime import date, timedelta

from langchain_core.tools import BaseTool, tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ConversationStatus
from app.repositories.conversations import ConversationRepository
from app.repositories.faq import FaqRepository
from app.repositories.tickets import TicketRepository
from app.tools.executor import ToolNotFoundError, current_tool_execution_context
from app.tools.schemas import (
    CreateTicketArgs,
    FaqKeywordArgs,
    OrderIdArgs,
    ProductKeywordArgs,
)


def build_business_tools(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    rng: random.Random | None = None,
) -> list[BaseTool]:
    random_source = rng or random.Random()

    @tool(
        "query_order",
        args_schema=OrderIdArgs,
        description="查询订单状态、金额和商品摘要。订单相关问题优先使用。",
    )
    async def query_order(order_id: str) -> dict[str, object]:
        return {
            "order_id": order_id,
            "status": random_source.choice(["待发货", "已发货", "已完成", "退款处理中"]),
            "amount": round(random_source.uniform(29, 999), 2),
            "product_summary": random_source.choice(
                ["像素风连帽衫 × 1", "复古机械键盘 × 1", "旅行收纳包 × 2"]
            ),
            "source": "demo",
        }

    @tool(
        "query_product",
        args_schema=ProductKeywordArgs,
        description="查询商品名称、库存、价格和上下架状态。商品咨询时使用。",
    )
    async def query_product(keyword: str) -> dict[str, object]:
        stock = random_source.randint(0, 80)
        return {
            "keyword": keyword,
            "product_name": f"{keyword}演示商品",
            "stock": stock,
            "price": round(random_source.uniform(19, 599), 2),
            "sale_status": "在售" if stock else "缺货",
            "source": "demo",
        }

    @tool(
        "query_logistics",
        args_schema=OrderIdArgs,
        description="查询指定订单的承运商、运单号、物流状态和预计送达时间。",
    )
    async def query_logistics(order_id: str) -> dict[str, object]:
        return {
            "order_id": order_id,
            "carrier": random_source.choice(["顺丰速运", "中通快递", "京东物流"]),
            "tracking_no": f"DEMO{random_source.randint(1000000000, 9999999999)}",
            "status": random_source.choice(["运输中", "派送中", "已签收"]),
            "current_location": random_source.choice(
                ["杭州转运中心", "上海分拨中心", "本地营业点"]
            ),
            "estimated_delivery": (date.today() + timedelta(days=2)).isoformat(),
            "source": "demo",
        }

    @tool(
        "query_faq",
        args_schema=FaqKeywordArgs,
        description="按关键词查询商城 FAQ。政策、退换货和常见场景问题时使用。",
    )
    async def query_faq(keyword: str) -> dict[str, object]:
        if session_factory is None:
            raise RuntimeError("数据库会话不可用")
        async with session_factory() as session:
            matches = await FaqRepository(session).search_by_question(keyword)
        if not matches:
            raise ToolNotFoundError
        return {
            "keyword": keyword,
            "matches": [
                {
                    "question": item.question,
                    "answer": item.answer,
                    "category": item.category,
                }
                for item in matches
            ],
        }

    @tool(
        "create_ticket",
        args_schema=CreateTicketArgs,
        description="用户明确要求人工处理时创建人工客服工单。",
    )
    async def create_ticket(issue_description: str, ticket_type: str) -> dict[str, object]:
        if session_factory is None:
            raise RuntimeError("数据库会话不可用")
        context = current_tool_execution_context()
        async with session_factory.begin() as session:
            conversations = ConversationRepository(session)
            await conversations.get_or_create(context.conversation_id, context.user_id)
            ticket = await TicketRepository(session).create_or_get(
                conversation_id=context.conversation_id,
                tool_call_id=context.tool_call_id,
                issue_description=issue_description,
                ticket_type=ticket_type,
            )
            await conversations.set_status(
                context.conversation_id,
                ConversationStatus.WAITING_HUMAN,
            )
        return {
            "ticket_no": ticket.ticket_no,
            "status": ticket.status.value,
            "ticket_type": ticket.ticket_type,
        }

    return [query_order, query_product, query_logistics, query_faq, create_ticket]
