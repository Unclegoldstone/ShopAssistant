from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.faq import Faq
from app.repositories.faq import FaqRepository
from app.schemas import FaqCreate, FaqItem, FaqUpdate
from app.services.knowledge_ingestion import deactivate_faq_knowledge, sync_faq_record


class FaqNotFoundError(LookupError):
    def __init__(self, faq_id: int) -> None:
        super().__init__(f"FAQ {faq_id} not found")
        self.faq_id = faq_id


class FaqReadOnlyError(PermissionError):
    pass


def _ensure_test_record(is_test: bool) -> None:
    if not is_test:
        raise FaqReadOnlyError("business FAQ records are read-only")


def _to_item(record: Faq) -> FaqItem:
    return FaqItem(
        id=record.id,
        question=record.question,
        answer=record.answer,
        category=record.category,
    )


class FaqCrudService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_items(self) -> list[FaqItem]:
        async with self._session_factory() as session:
            records = await FaqRepository(session).list_all()
            return [_to_item(record) for record in records]

    async def create(self, payload: FaqCreate) -> FaqItem:
        async with self._session_factory.begin() as session:
            record = await FaqRepository(session).add(
                **payload.model_dump(),
                is_test=True,
            )
            await sync_faq_record(session, record)
            return _to_item(record)

    async def update(self, faq_id: int, payload: FaqUpdate) -> FaqItem:
        async with self._session_factory.begin() as session:
            record = await FaqRepository(session).get(faq_id)
            if record is None:
                raise FaqNotFoundError(faq_id)
            record.question = payload.question
            record.answer = payload.answer
            record.category = payload.category
            await session.flush()
            await sync_faq_record(session, record)
            return _to_item(record)

    async def delete(self, faq_id: int) -> None:
        async with self._session_factory.begin() as session:
            repository = FaqRepository(session)
            record = await repository.get(faq_id)
            if record is None:
                raise FaqNotFoundError(faq_id)
            _ensure_test_record(record.is_test)
            await deactivate_faq_knowledge(session, record.id)
            await repository.delete(record)
