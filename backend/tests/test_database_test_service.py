from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.db.session import create_database_runtime
from app.models.faq import Faq
from app.services.database_test import DatabaseTestService


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="set SHOP_ASSISTANT_RUN_MYSQL_TESTS=1 to run MySQL integration tests",
)
@pytest.mark.asyncio
async def test_database_test_service_runs_crud_and_removes_temporary_row() -> None:
    runtime = create_database_runtime(Settings())
    service = DatabaseTestService(runtime.session_factory)

    try:
        result = await service.run()

        assert result.ok is True
        assert [step.operation for step in result.steps] == [
            "connect",
            "create",
            "read",
            "update",
            "delete",
        ]
        assert all(step.ok for step in result.steps)

        async with runtime.session_factory() as session:
            remaining = await session.scalar(
                select(func.count(Faq.id)).where(
                    Faq.question.like(f"{DatabaseTestService.QUESTION_PREFIX}%")
                )
            )
        assert remaining == 0
    finally:
        await runtime.dispose()
