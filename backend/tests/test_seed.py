from __future__ import annotations

import os

import pytest
from sqlalchemy import delete, func, select

from app.config import Settings
from app.db.session import create_database_runtime
from app.models import Faq
from scripts.seed_demo_data import DEMO_FAQS, seed_demo_faqs


def test_demo_faqs_preserve_the_expected_shipping_recall_gap() -> None:
    questions = [item["question"] for item in DEMO_FAQS]
    corpus = " ".join(
        f"{item['question']} {item['answer']} {item['category']}" for item in DEMO_FAQS
    )

    assert "退货政策是什么" in questions
    assert len(questions) == len(set(questions))
    assert "邮费" not in corpus
    assert "运费" not in corpus


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the migrated Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_seed_is_idempotent() -> None:
    runtime = create_database_runtime(Settings())
    questions = [item["question"] for item in DEMO_FAQS]

    try:
        async with runtime.session_factory() as session:
            await session.execute(delete(Faq).where(Faq.question.in_(questions)))
            await session.commit()

        assert await seed_demo_faqs(runtime.session_factory) == len(DEMO_FAQS)
        assert await seed_demo_faqs(runtime.session_factory) == 0

        async with runtime.session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(Faq).where(Faq.question.in_(questions))
            )

        assert count == len(DEMO_FAQS)
    finally:
        await runtime.dispose()
