from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Faq


class FaqRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_by_question(self, keyword: str, *, limit: int = 5) -> list[Faq]:
        statement = (
            select(Faq).where(Faq.question.like(f"%{keyword}%")).order_by(Faq.id).limit(limit)
        )
        return list(await self._session.scalars(statement))

    async def list_all(self, *, limit: int = 100) -> list[Faq]:
        statement = select(Faq).order_by(Faq.id.desc()).limit(limit)
        return list(await self._session.scalars(statement))

    async def get(self, faq_id: int) -> Faq | None:
        return await self._session.get(Faq, faq_id)

    async def add(
        self,
        *,
        question: str,
        answer: str,
        category: str,
        is_test: bool = False,
    ) -> Faq:
        item = Faq(
            question=question,
            answer=answer,
            category=category,
            is_test=is_test,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def delete(self, item: Faq) -> None:
        await self._session.delete(item)
        await self._session.flush()
