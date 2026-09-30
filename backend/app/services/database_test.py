from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.faq import Faq
from app.schemas import DatabaseTestResult, DatabaseTestStep


class DatabaseTestService:
    """Run a disposable database CRUD check without exposing arbitrary SQL."""

    QUESTION_PREFIX = "[SHOP_ASSISTANT_DB_TEST]"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def run(self) -> DatabaseTestResult:
        question = f"{self.QUESTION_PREFIX} {uuid4()}"
        original_answer = "create-ok"
        updated_answer = "update-ok"
        steps: list[DatabaseTestStep] = []

        async with self._session_factory.begin() as session:
            database_name = await session.scalar(text("SELECT DATABASE()"))
            steps.append(
                DatabaseTestStep(
                    operation="connect",
                    ok=bool(database_name),
                    detail="数据库连接正常",
                )
            )

            temporary_faq = Faq(
                question=question,
                answer=original_answer,
                category="系统自检",
                is_test=True,
            )
            session.add(temporary_faq)
            await session.flush()
            temporary_id = temporary_faq.id
            steps.append(
                DatabaseTestStep(
                    operation="create",
                    ok=True,
                    detail=f"临时记录 #{temporary_id} 新增成功",
                )
            )

            stored_answer = await session.scalar(
                select(Faq.answer).where(Faq.id == temporary_id)
            )
            if stored_answer != original_answer:
                raise RuntimeError("database read verification failed")
            steps.append(
                DatabaseTestStep(
                    operation="read",
                    ok=True,
                    detail="临时记录查询成功",
                )
            )

            await session.execute(
                update(Faq)
                .where(Faq.id == temporary_id)
                .values(answer=updated_answer)
            )
            stored_answer = await session.scalar(
                select(Faq.answer).where(Faq.id == temporary_id)
            )
            if stored_answer != updated_answer:
                raise RuntimeError("database update verification failed")
            steps.append(
                DatabaseTestStep(
                    operation="update",
                    ok=True,
                    detail="临时记录更新成功",
                )
            )

            await session.execute(delete(Faq).where(Faq.id == temporary_id))
            remaining = await session.scalar(
                select(func.count(Faq.id)).where(Faq.id == temporary_id)
            )
            if remaining != 0:
                raise RuntimeError("database delete verification failed")
            steps.append(
                DatabaseTestStep(
                    operation="delete",
                    ok=True,
                    detail="临时记录删除成功，未保留测试数据",
                )
            )

        return DatabaseTestResult(
            ok=all(step.ok for step in steps),
            database=str(database_name),
            steps=steps,
        )
