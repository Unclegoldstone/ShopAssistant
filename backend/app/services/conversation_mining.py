from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.knowledge.text import build_content_fingerprint
from app.knowledge.types import KnowledgeDraft
from app.models import (
    Conversation,
    ConversationStatus,
    KnowledgeContentType,
    KnowledgeMiningRun,
    KnowledgeMiningRunStatus,
    KnowledgeSourceType,
    KnowledgeStaging,
    KnowledgeStagingStatus,
    Message,
    MessageRole,
)
from app.prompts import conversation_knowledge_extraction_prompt
from app.repositories.knowledge import sanitize_error_summary


class ExtractedKnowledge(BaseModel):
    turn_index: int
    category: str
    questions: list[str]
    answer: str
    is_critical: bool
    should_store: bool
    reason: str

    @field_validator("category", "answer", "reason")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("文本字段不能为空")
        return value

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, value: list[str]) -> list[str]:
        questions = [item.strip() for item in value if item.strip()]
        if not questions:
            raise ValueError("questions 不能为空")
        return questions

    @field_validator("turn_index")
    @classmethod
    def validate_turn_index(cls, value: int) -> int:
        if value < 0:
            raise ValueError("turn_index 不能为负数")
        return value


class ExtractedKnowledgeBatch(BaseModel):
    items: list[ExtractedKnowledge]


@dataclass(frozen=True, slots=True)
class MiningMessage:
    id: int
    conversation_id: str
    conversation_status: ConversationStatus
    role: MessageRole
    content: str
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class VisibleTurn:
    conversation_id: str
    first_message_id: int
    last_message_id: int
    user_content: str
    assistant_content: str


@dataclass(frozen=True, slots=True)
class MiningResult:
    batch_id: str | None
    processed_turns: int
    extracted: int
    stored: int
    cursor_end_message_id: int | None


def assemble_visible_turns(messages: Sequence[MiningMessage]) -> list[VisibleTurn]:
    pending_users: dict[str, MiningMessage] = {}
    turns: list[VisibleTurn] = []
    for message in sorted(messages, key=lambda item: item.id):
        if message.conversation_status is ConversationStatus.FAILED:
            continue
        content = message.content.strip()
        if message.role is MessageRole.USER and content:
            pending_users[message.conversation_id] = message
            continue
        if (
            message.role is not MessageRole.ASSISTANT
            or message.tool_calls
            or message.tool_call_id
            or not content
        ):
            continue
        user = pending_users.pop(message.conversation_id, None)
        if user is None:
            continue
        turns.append(
            VisibleTurn(
                conversation_id=message.conversation_id,
                first_message_id=user.id,
                last_message_id=message.id,
                user_content=user.content.strip(),
                assistant_content=content,
            )
        )
    return turns


def select_turns_within_budget(
    turns: Sequence[VisibleTurn],
    *,
    token_budget: int,
    token_counter: Callable[[str], int],
) -> list[VisibleTurn]:
    if token_budget <= 0:
        raise ValueError("token_budget 必须为正数")
    selected: list[VisibleTurn] = []
    used = 0
    for turn in turns:
        cost = token_counter(f"{turn.user_content}\n{turn.assistant_content}")
        if selected and used + cost > token_budget:
            break
        selected.append(turn)
        used += cost
    return selected


class ConversationMiningService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        model: Any,
        batch_size: int,
        token_budget: int,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._structured_model = model.with_structured_output(
            ExtractedKnowledgeBatch,
            method="json_schema",
            strict=True,
        )
        self._batch_size = batch_size
        self._token_budget = token_budget
        self._token_counter = token_counter or _estimate_tokens

    async def run_once(self) -> MiningResult:
        cursor = await self._latest_cursor()
        messages = await self._load_messages_after(cursor)
        turns = select_turns_within_budget(
            assemble_visible_turns(messages)[: self._batch_size],
            token_budget=self._token_budget,
            token_counter=self._token_counter,
        )
        if not turns:
            return MiningResult(None, 0, 0, 0, cursor)

        batch_id = uuid4().hex
        transcript = json.dumps(
            [
                {
                    "turn_index": index,
                    "user": turn.user_content,
                    "assistant": turn.assistant_content,
                }
                for index, turn in enumerate(turns)
            ],
            ensure_ascii=False,
        )
        try:
            messages_for_model = conversation_knowledge_extraction_prompt.format_messages(
                transcript=transcript
            )
            raw_result = await self._structured_model.ainvoke(messages_for_model)
            extracted = (
                raw_result
                if isinstance(raw_result, ExtractedKnowledgeBatch)
                else ExtractedKnowledgeBatch.model_validate(raw_result)
            )
            stored = await self._persist_batch(batch_id, cursor, turns, extracted)
        except Exception as exc:
            await self._record_failed_run(batch_id, cursor, exc)
            raise
        return MiningResult(
            batch_id=batch_id,
            processed_turns=len(turns),
            extracted=len(extracted.items),
            stored=stored,
            cursor_end_message_id=max(turn.last_message_id for turn in turns),
        )

    async def _latest_cursor(self) -> int | None:
        async with self._session_factory() as session:
            statement = select(func.max(KnowledgeMiningRun.cursor_end_message_id)).where(
                KnowledgeMiningRun.status == KnowledgeMiningRunStatus.COMPLETED
            )
            return await session.scalar(statement)

    async def _load_messages_after(self, cursor: int | None) -> list[MiningMessage]:
        async with self._session_factory() as session:
            statement = (
                select(Message, Conversation.status)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(Message.id > (cursor or 0))
                .order_by(Message.id)
                .limit(max(self._batch_size * 20, 100))
            )
            rows = (await session.execute(statement)).all()
        return [
            MiningMessage(
                id=message.id,
                conversation_id=message.conversation_id,
                conversation_status=status,
                role=message.role,
                content=message.content,
                tool_calls=message.tool_calls,
                tool_call_id=message.tool_call_id,
                created_at=message.created_at,
            )
            for message, status in rows
        ]

    async def _persist_batch(
        self,
        batch_id: str,
        cursor: int | None,
        turns: Sequence[VisibleTurn],
        result: ExtractedKnowledgeBatch,
    ) -> int:
        stored = 0
        async with self._session_factory.begin() as session:
            run = KnowledgeMiningRun(
                batch_id=batch_id,
                status=KnowledgeMiningRunStatus.RUNNING,
                cursor_start_message_id=cursor,
                cursor_end_message_id=max(turn.last_message_id for turn in turns),
                processed_conversations=len({turn.conversation_id for turn in turns}),
                processed_messages=len(turns) * 2,
                extracted_count=len(result.items),
            )
            session.add(run)
            await session.flush()
            indexes_by_turn: dict[int, int] = {}
            for item in result.items:
                if not item.should_store or item.turn_index >= len(turns):
                    continue
                turn = turns[item.turn_index]
                item_index = indexes_by_turn.get(item.turn_index, 0)
                indexes_by_turn[item.turn_index] = item_index + 1
                await self._upsert_staging(session, run.id, turn, item_index, item)
                stored += 1
            run.status = KnowledgeMiningRunStatus.COMPLETED
            run.finished_at = datetime.now(UTC).replace(tzinfo=None)
        return stored

    async def _upsert_staging(
        self,
        session: AsyncSession,
        run_id: int,
        turn: VisibleTurn,
        item_index: int,
        item: ExtractedKnowledge,
    ) -> None:
        statement = select(KnowledgeStaging).where(
            KnowledgeStaging.conversation_id == turn.conversation_id,
            KnowledgeStaging.first_message_id == turn.first_message_id,
            KnowledgeStaging.last_message_id == turn.last_message_id,
            KnowledgeStaging.item_index == item_index,
        )
        staging = await session.scalar(statement)
        draft = KnowledgeDraft(
            source_type=KnowledgeSourceType.CONVERSATION,
            source_key=(
                f"conversation:{turn.conversation_id}:"
                f"{turn.first_message_id}-{turn.last_message_id}:{item_index}"
            ),
            source_revision="extracted",
            category=item.category,
            questions=tuple(item.questions),
            answer=item.answer,
            section_path=("历史客服对话", item.category),
            content_type=KnowledgeContentType.CONVERSATION_QA,
            is_critical=item.is_critical,
        )
        values = {
            "mining_run_id": run_id,
            "category": draft.category,
            "questions": list(draft.questions),
            "answer": draft.answer,
            "is_critical": draft.is_critical,
            "content_fingerprint": build_content_fingerprint(draft),
            "status": KnowledgeStagingStatus.EXTRACTED,
            "decision_reason": item.reason,
            "error_summary": None,
            "extraction_payload": item.model_dump(mode="json"),
        }
        if staging is None:
            staging = KnowledgeStaging(
                conversation_id=turn.conversation_id,
                first_message_id=turn.first_message_id,
                last_message_id=turn.last_message_id,
                item_index=item_index,
                **values,
            )
            session.add(staging)
        else:
            for field, value in values.items():
                setattr(staging, field, value)
        await session.flush()

    async def _record_failed_run(
        self,
        batch_id: str,
        cursor: int | None,
        error: Exception,
    ) -> None:
        async with self._session_factory.begin() as session:
            session.add(
                KnowledgeMiningRun(
                    batch_id=batch_id,
                    status=KnowledgeMiningRunStatus.FAILED,
                    cursor_start_message_id=cursor,
                    error_summary=sanitize_error_summary(error),
                    finished_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 1) // 2)
