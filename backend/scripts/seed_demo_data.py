from __future__ import annotations

import asyncio
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.session import create_database_runtime
from app.models import Faq


class DemoFaq(TypedDict):
    question: str
    answer: str
    category: str


DEMO_FAQS: tuple[DemoFaq, ...] = (
    {
        "question": "退货政策是什么",
        "answer": (
            "演示商城支持符合条件的商品在签收后 7 天内申请退货，"
            "商品需保持完好并保留完整包装与附件。"
        ),
        "category": "售后",
    },
    {
        "question": "如何申请换货",
        "answer": "请提供订单号、需要更换的商品和原因，客服确认商品状态后会协助提交换货申请。",
        "category": "售后",
    },
    {
        "question": "如何开具发票",
        "answer": "请在订单完成后提供订单号、发票抬头和税号，客服会协助登记开票信息。",
        "category": "订单",
    },
)


async def seed_demo_faqs(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    questions = [item["question"] for item in DEMO_FAQS]

    async with session_factory() as session:
        existing_questions = set(
            await session.scalars(select(Faq.question).where(Faq.question.in_(questions)))
        )
        new_items = [
            Faq(**item) for item in DEMO_FAQS if item["question"] not in existing_questions
        ]
        session.add_all(new_items)
        await session.commit()

    return len(new_items)


async def main() -> None:
    runtime = create_database_runtime(Settings())
    try:
        inserted_count = await seed_demo_faqs(runtime.session_factory)
        print(f"FAQ seed complete: inserted={inserted_count}, total_demo={len(DEMO_FAQS)}")
    finally:
        await runtime.dispose()


if __name__ == "__main__":
    asyncio.run(main())
