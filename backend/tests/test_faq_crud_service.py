from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.config import Settings
from app.db.session import create_database_runtime
from app.models import KnowledgeChunk, KnowledgeVectorStatus
from app.models.faq import Faq
from app.repositories.knowledge import KnowledgeRepository
from app.schemas import FaqCreate, FaqUpdate
from app.services.faq_crud import FaqCrudService, FaqReadOnlyError


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="set SHOP_ASSISTANT_RUN_MYSQL_TESTS=1 to run MySQL integration tests",
)
@pytest.mark.asyncio
async def test_faq_crud_service_runs_common_database_operations() -> None:
    runtime = create_database_runtime(Settings())
    marker = f"CRUD-{uuid4().hex}"
    service = FaqCrudService(runtime.session_factory)
    created_id: int | None = None

    try:
        protected = next(
            item for item in await service.list_items() if item.question == "退货政策是什么"
        )
        original_protected = FaqUpdate(
            question=protected.question,
            answer=protected.answer,
            category=protected.category,
        )
        updated_protected = await service.update(
            protected.id,
            FaqUpdate(
                question=protected.question,
                answer=f"{protected.answer}（更新测试）",
                category=protected.category,
            ),
        )
        assert updated_protected.answer.endswith("（更新测试）")
        await service.update(protected.id, original_protected)
        with pytest.raises(FaqReadOnlyError):
            await service.delete(protected.id)

        created = await service.create(
            FaqCreate(question=marker, answer="创建成功", category="自定义分类")
        )
        created_id = created.id
        assert any(item.id == created.id for item in await service.list_items())
        async with runtime.session_factory.begin() as session:
            knowledge = await KnowledgeRepository(session).get_by_source_key(f"faq:{created.id}")
            assert knowledge is not None
            assert knowledge.vector_status is KnowledgeVectorStatus.PENDING
            await KnowledgeRepository(session).mark_vectorized(
                knowledge.id,
                vector_id=str(knowledge.id),
                embedding_model="fake-bge",
                embedding_version="v1",
            )

        updated = await service.update(
            created.id,
            FaqUpdate(question=marker, answer="更新成功", category="更新后的分类"),
        )
        assert updated.answer == "更新成功"
        assert updated.category == "更新后的分类"
        async with runtime.session_factory() as session:
            knowledge = await KnowledgeRepository(session).get_by_source_key(f"faq:{created.id}")
            assert knowledge is not None
            assert knowledge.answer == "更新成功"
            assert knowledge.vector_status is KnowledgeVectorStatus.PENDING

        await service.delete(created.id)
        async with runtime.session_factory() as session:
            knowledge = await KnowledgeRepository(session).get_by_source_key(f"faq:{created.id}")
            assert knowledge is not None
            assert knowledge.is_active is False
            assert knowledge.vector_status is KnowledgeVectorStatus.PENDING_DELETE
        created_id = None
        assert all(item.id != created.id for item in await service.list_items())
    finally:
        if created_id is not None:
            async with runtime.session_factory.begin() as session:
                await session.execute(delete(Faq).where(Faq.id == created_id))
        async with runtime.session_factory.begin() as session:
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.source_key == f"faq:{created.id}")
                if "created" in locals()
                else delete(KnowledgeChunk).where(KnowledgeChunk.source_key == "missing")
            )
        await runtime.dispose()
