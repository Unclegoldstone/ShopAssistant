from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.config import Settings
from app.db.session import create_database_runtime
from app.knowledge.types import KnowledgeDraft
from app.models import (
    KnowledgeChunk,
    KnowledgeContentType,
    KnowledgeSourceType,
    KnowledgeVectorStatus,
)
from app.repositories.knowledge import KnowledgeRepository


def make_draft(source_key: str, **overrides: object) -> KnowledgeDraft:
    values: dict[str, object] = {
        "source_type": KnowledgeSourceType.MARKDOWN,
        "source_key": source_key,
        "source_revision": "revision-1",
        "category": "配送政策",
        "questions": ("运费是多少?",),
        "answer": "普通地区订单满 99 元包邮。",
        "section_path": ("配送政策", "运费规则"),
        "content_type": KnowledgeContentType.POLICY,
        "is_critical": False,
    }
    values.update(overrides)
    return KnowledgeDraft(**values)  # type: ignore[arg-type]


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the migrated Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_content_change_reuses_primary_key() -> None:
    runtime = create_database_runtime(Settings())
    prefix = f"test:knowledge:{uuid4().hex}"

    try:
        async with runtime.session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            first = await repository.upsert_chunk(make_draft(f"{prefix}:one"))
            await repository.mark_vectorized(
                first.chunk.id,
                vector_id=str(first.chunk.id),
                embedding_model="BAAI/bge-m3",
                embedding_version="revision-a",
            )

        async with runtime.session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            unchanged = await repository.upsert_chunk(make_draft(f"{prefix}:one"))

        assert unchanged.chunk.id == first.chunk.id
        assert unchanged.created is False
        assert unchanged.changed is False
        assert unchanged.chunk.vector_status is KnowledgeVectorStatus.VECTORIZED

        changed_draft = replace(
            make_draft(f"{prefix}:one"),
            source_revision="revision-2",
            answer="普通地区订单满 79 元包邮。",
        )
        async with runtime.session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            changed = await repository.upsert_chunk(changed_draft)
            second = await repository.upsert_chunk(make_draft(f"{prefix}:two"))

        assert changed.chunk.id == first.chunk.id
        assert changed.changed is True
        assert changed.chunk.vector_status is KnowledgeVectorStatus.PENDING
        assert changed.chunk.vector_id == str(first.chunk.id)
        assert changed.chunk.vector_error is None
        assert changed.chunk.vector_attempts == 0

        async with runtime.session_factory() as session:
            ordered = await KnowledgeRepository(session).get_by_ids_in_order(
                [second.chunk.id, changed.chunk.id, 999999999]
            )
        assert [item.id for item in ordered] == [second.chunk.id, changed.chunk.id]

        async with runtime.session_factory.begin() as session:
            pending_delete = await KnowledgeRepository(session).mark_pending_delete(
                second.chunk.id
            )
        assert pending_delete.is_active is False
        assert pending_delete.vector_status is KnowledgeVectorStatus.PENDING_DELETE

        async with runtime.session_factory.begin() as session:
            reactivated = await KnowledgeRepository(session).upsert_chunk(
                make_draft(f"{prefix}:two")
            )
        assert reactivated.changed is True
        assert reactivated.chunk.is_active is True
        assert reactivated.chunk.vector_status is KnowledgeVectorStatus.PENDING

        async with runtime.session_factory.begin() as session:
            inconsistent = await KnowledgeRepository(session).get(second.chunk.id)
            assert inconsistent is not None
            inconsistent.vector_status = KnowledgeVectorStatus.PENDING_DELETE
            inconsistent.vector_id = None
        async with runtime.session_factory.begin() as session:
            repaired = await KnowledgeRepository(session).upsert_chunk(
                make_draft(f"{prefix}:two")
            )
        assert repaired.changed is True
        assert repaired.chunk.vector_status is KnowledgeVectorStatus.PENDING
    finally:
        async with runtime.session_factory.begin() as session:
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.source_key.like(f"{prefix}%"))
            )
        await runtime.dispose()


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the migrated Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_deactivate_missing_markdown_does_not_touch_kb_upload_sources() -> None:
    runtime = create_database_runtime(Settings())
    suffix = uuid4().hex
    official_key = f"markdown:test-{suffix}.md:root:0"
    upload_key = f"kb_upload:test-{suffix}.md:root:0"
    try:
        async with runtime.session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            official = (await repository.upsert_chunk(make_draft(official_key))).chunk
            upload = (await repository.upsert_chunk(make_draft(upload_key))).chunk
            changed = await repository.deactivate_missing_sources(
                KnowledgeSourceType.MARKDOWN,
                active_source_keys=set(),
                source_key_prefix=f"markdown:test-{suffix}",
            )

        assert changed == 1
        assert official.is_active is False
        assert upload.is_active is True
    finally:
        async with runtime.session_factory.begin() as session:
            await session.execute(
                delete(KnowledgeChunk).where(
                    KnowledgeChunk.source_key.in_([official_key, upload_key])
                )
            )
        await runtime.dispose()


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the migrated Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_vector_claim_retries_failed_and_expired_leases() -> None:
    runtime = create_database_runtime(Settings())
    prefix = f"test:knowledge:{uuid4().hex}"
    now = datetime.now(UTC).replace(tzinfo=None)

    try:
        async with runtime.session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            pending = (await repository.upsert_chunk(make_draft(f"{prefix}:pending"))).chunk
            failed = (await repository.upsert_chunk(make_draft(f"{prefix}:failed"))).chunk
            expired = (await repository.upsert_chunk(make_draft(f"{prefix}:expired"))).chunk
            await repository.mark_failed(failed.id, "api_key=secret\nnetwork failed")
            expired.vector_status = KnowledgeVectorStatus.VECTORIZING
            expired.vectorizing_started_at = now - timedelta(minutes=10)

        async with runtime.session_factory.begin() as session:
            claimed = await KnowledgeRepository(session).claim_for_vectorization(
                limit=10,
                lease_timeout=timedelta(minutes=5),
                max_attempts=3,
                now=now,
                chunk_ids=[pending.id, failed.id, expired.id],
            )

        assert {item.id for item in claimed} == {pending.id, failed.id, expired.id}
        assert all(item.vector_status is KnowledgeVectorStatus.VECTORIZING for item in claimed)
        assert all(item.vectorizing_started_at == now for item in claimed)
        assert failed.vector_error is not None
        assert "\n" not in failed.vector_error
        assert "secret" not in failed.vector_error
    finally:
        async with runtime.session_factory.begin() as session:
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.source_key.like(f"{prefix}%"))
            )
        await runtime.dispose()


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the migrated Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_concurrent_claims_skip_rows_locked_by_another_worker() -> None:
    runtime = create_database_runtime(Settings())
    prefix = f"test:knowledge:{uuid4().hex}"

    try:
        async with runtime.session_factory.begin() as setup_session:
            repository = KnowledgeRepository(setup_session)
            first = (await repository.upsert_chunk(make_draft(f"{prefix}:one"))).chunk
            second = (await repository.upsert_chunk(make_draft(f"{prefix}:two"))).chunk
        candidate_ids = [first.id, second.id]

        async with runtime.session_factory() as first_session:
            async with first_session.begin():
                first_claim = await KnowledgeRepository(
                    first_session
                ).claim_for_vectorization(
                    limit=1,
                    lease_timeout=timedelta(minutes=5),
                    max_attempts=3,
                    chunk_ids=candidate_ids,
                )
                async with runtime.session_factory.begin() as second_session:
                    second_claim = await KnowledgeRepository(
                        second_session
                    ).claim_for_vectorization(
                        limit=2,
                        lease_timeout=timedelta(minutes=5),
                        max_attempts=3,
                        chunk_ids=candidate_ids,
                    )

        assert len(first_claim) == 1
        assert len(second_claim) == 1
        assert first_claim[0].id != second_claim[0].id
    finally:
        async with runtime.session_factory.begin() as session:
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.source_key.like(f"{prefix}%"))
            )
        await runtime.dispose()
