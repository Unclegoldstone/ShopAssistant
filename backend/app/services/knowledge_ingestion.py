from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.knowledge.markdown import MarkdownKnowledgeSplitter
from app.knowledge.types import KnowledgeDraft
from app.models import Faq, KnowledgeContentType, KnowledgeSourceType
from app.repositories.knowledge import KnowledgeRepository


@dataclass(frozen=True, slots=True)
class LinkedKnowledgeDraft:
    draft: KnowledgeDraft
    previous_source_key: str | None
    next_source_key: str | None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    scanned: int = 0
    created: int = 0
    changed: int = 0
    unchanged: int = 0
    deactivated: int = 0


def load_markdown_drafts(
    source_root: Path,
    *,
    splitter: MarkdownKnowledgeSplitter,
) -> list[LinkedKnowledgeDraft]:
    items: list[LinkedKnowledgeDraft] = []
    for path in sorted(source_root.rglob("*.md")):
        relative_path = PurePosixPath(path.relative_to(source_root).as_posix()).as_posix()
        chunks = splitter.split(relative_path, path.read_text(encoding="utf-8"))
        drafts = [chunk.to_draft() for chunk in chunks]
        for index, draft in enumerate(drafts):
            items.append(
                LinkedKnowledgeDraft(
                    draft=draft,
                    previous_source_key=drafts[index - 1].source_key if index > 0 else None,
                    next_source_key=(
                        drafts[index + 1].source_key if index + 1 < len(drafts) else None
                    ),
                )
            )
    return items


def faq_to_draft(faq: Any) -> KnowledgeDraft:
    revision_payload = json.dumps(
        {
            "question": faq.question,
            "answer": faq.answer,
            "category": faq.category,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    revision = hashlib.sha256(revision_payload.encode("utf-8")).hexdigest()
    return KnowledgeDraft(
        source_type=KnowledgeSourceType.FAQ,
        source_key=f"faq:{faq.id}",
        source_revision=revision,
        category=faq.category,
        questions=(faq.question,),
        answer=faq.answer,
        section_path=("FAQ", faq.category),
        content_type=KnowledgeContentType.PRODUCT_FAQ,
        is_critical=False,
    )


async def sync_faq_record(session: AsyncSession, faq: Faq) -> None:
    await KnowledgeRepository(session).upsert_chunk(faq_to_draft(faq))


async def deactivate_faq_knowledge(session: AsyncSession, faq_id: int) -> None:
    repository = KnowledgeRepository(session)
    chunk = await repository.get_by_source_key(f"faq:{faq_id}")
    if chunk is not None:
        await repository.mark_pending_delete(chunk.id)


class KnowledgeIngestionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        splitter: MarkdownKnowledgeSplitter,
    ) -> None:
        self._session_factory = session_factory
        self._splitter = splitter

    async def ingest_markdown(self, source_root: Path) -> IngestionResult:
        items = load_markdown_drafts(source_root, splitter=self._splitter)
        async with self._session_factory.begin() as session:
            repository = KnowledgeRepository(session)
            results = [await repository.upsert_chunk(item.draft) for item in items]
            by_source_key = {result.chunk.source_key: result.chunk for result in results}
            for item in items:
                chunk = by_source_key[item.draft.source_key]
                previous = by_source_key.get(item.previous_source_key)
                following = by_source_key.get(item.next_source_key)
                await repository.set_neighbors(
                    chunk.id,
                    previous_chunk_id=previous.id if previous else None,
                    next_chunk_id=following.id if following else None,
                )
            deactivated = await repository.deactivate_missing_sources(
                KnowledgeSourceType.MARKDOWN,
                set(by_source_key),
                source_key_prefix="markdown:",
            )
        return _summarize(results, deactivated=deactivated)

    async def ingest_faqs(self) -> IngestionResult:
        async with self._session_factory.begin() as session:
            faqs = list(await session.scalars(select(Faq).order_by(Faq.id)))
            repository = KnowledgeRepository(session)
            results = [await repository.upsert_chunk(faq_to_draft(faq)) for faq in faqs]
            deactivated = await repository.deactivate_missing_sources(
                KnowledgeSourceType.FAQ,
                {result.chunk.source_key for result in results},
                source_key_prefix="faq:",
            )
        return _summarize(results, deactivated=deactivated)


def _summarize(results: list[Any], *, deactivated: int) -> IngestionResult:
    created = sum(result.created for result in results)
    changed = sum(result.changed and not result.created for result in results)
    return IngestionResult(
        scanned=len(results),
        created=created,
        changed=changed,
        unchanged=len(results) - created - changed,
        deactivated=deactivated,
    )
