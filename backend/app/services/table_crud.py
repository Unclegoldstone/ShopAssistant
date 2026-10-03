from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    Conversation,
    ConversationStatus,
    Faq,
    Message,
    MessageRole,
    Ticket,
    TicketStatus,
)
from app.schemas import DatabaseTableName, TableRecord, TableRecordWrite
from app.services.knowledge_ingestion import deactivate_faq_knowledge, sync_faq_record

TEST_CONVERSATION_PREFIX = "test-lab-"
TEST_TICKET_PREFIX = "TL-"


class TableRecordNotFoundError(LookupError):
    pass


class TableRecordConflictError(RuntimeError):
    pass


class TableRecordValidationError(ValueError):
    pass


class TableRecordReadOnlyError(PermissionError):
    pass


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _FaqInput(_StrictInput):
    question: str = Field(min_length=1, max_length=255)
    answer: str = Field(min_length=1, max_length=10000)
    category: str = Field(min_length=1, max_length=64)


class _ConversationCreate(_StrictInput):
    id: str = Field(
        min_length=len(TEST_CONVERSATION_PREFIX) + 1,
        max_length=128,
        pattern=r"^test-lab-[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    user_id: str = Field(min_length=1, max_length=64)
    status: ConversationStatus = ConversationStatus.ACTIVE


class _ConversationUpdate(_StrictInput):
    user_id: str = Field(min_length=1, max_length=64)
    status: ConversationStatus


class _MessageInput(_StrictInput):
    conversation_id: str = Field(
        min_length=len(TEST_CONVERSATION_PREFIX) + 1,
        max_length=128,
        pattern=r"^test-lab-",
    )
    role: MessageRole
    content: str = Field(min_length=1, max_length=100000)
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = Field(default=None, max_length=128)


class _TicketCreate(_StrictInput):
    ticket_no: str = Field(
        min_length=len(TEST_TICKET_PREFIX) + 1,
        max_length=32,
        pattern=r"^TL-[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    conversation_id: str = Field(
        min_length=len(TEST_CONVERSATION_PREFIX) + 1,
        max_length=128,
        pattern=r"^test-lab-",
    )
    issue_description: str = Field(min_length=1, max_length=10000)
    ticket_type: str = Field(min_length=1, max_length=64)
    status: TicketStatus = TicketStatus.OPEN


class _TicketUpdate(_StrictInput):
    conversation_id: str = Field(
        min_length=len(TEST_CONVERSATION_PREFIX) + 1,
        max_length=128,
        pattern=r"^test-lab-",
    )
    issue_description: str = Field(min_length=1, max_length=10000)
    ticket_type: str = Field(min_length=1, max_length=64)
    status: TicketStatus


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _is_test_record(item: Faq | Conversation | Message | Ticket) -> bool:
    if isinstance(item, Faq):
        return item.is_test
    if isinstance(item, Conversation):
        return item.id.startswith(TEST_CONVERSATION_PREFIX)
    if isinstance(item, Message):
        return item.conversation_id.startswith(TEST_CONVERSATION_PREFIX)
    return item.ticket_no.startswith(TEST_TICKET_PREFIX) and item.conversation_id.startswith(
        TEST_CONVERSATION_PREFIX
    )


def _can_update(item: Faq | Conversation | Message | Ticket) -> bool:
    return isinstance(item, Faq) or _is_test_record(item)


def _to_record(item: Faq | Conversation | Message | Ticket) -> TableRecord:
    can_update = _can_update(item)
    can_delete = _is_test_record(item)
    permissions = {
        "editable": can_update and can_delete,
        "can_update": can_update,
        "can_delete": can_delete,
    }
    if isinstance(item, Faq):
        return TableRecord(
            key=str(item.id),
            **permissions,
            values={
                "id": item.id,
                "question": item.question,
                "answer": item.answer,
                "category": item.category,
            },
        )
    if isinstance(item, Conversation):
        return TableRecord(
            key=item.id,
            **permissions,
            values={
                "id": item.id,
                "user_id": item.user_id,
                "status": item.status.value,
                "created_at": _timestamp(item.created_at),
            },
        )
    if isinstance(item, Message):
        return TableRecord(
            key=str(item.id),
            **permissions,
            values={
                "id": item.id,
                "conversation_id": item.conversation_id,
                "role": item.role.value,
                "content": item.content,
                "tool_calls": item.tool_calls,
                "tool_call_id": item.tool_call_id,
                "created_at": _timestamp(item.created_at),
            },
        )
    return TableRecord(
        key=item.ticket_no,
        **permissions,
        values={
            "ticket_no": item.ticket_no,
            "conversation_id": item.conversation_id,
            "issue_description": item.issue_description,
            "ticket_type": item.ticket_type,
            "status": item.status.value,
            "created_at": _timestamp(item.created_at),
        },
    )


class TableCrudService:
    _models = {
        "faq": Faq,
        "conversations": Conversation,
        "messages": Message,
        "tickets": Ticket,
    }
    _primary_keys = {
        "faq": Faq.id,
        "conversations": Conversation.id,
        "messages": Message.id,
        "tickets": Ticket.ticket_no,
    }

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_records(self, table_name: DatabaseTableName) -> list[TableRecord]:
        model = self._models[table_name]
        primary_key = self._primary_keys[table_name]
        async with self._session_factory() as session:
            records = list(
                await session.scalars(select(model).order_by(primary_key.desc()).limit(100))
            )
            return [_to_record(record) for record in records]

    async def create(
        self,
        table_name: DatabaseTableName,
        payload: TableRecordWrite,
    ) -> TableRecord:
        try:
            values = self._validate(table_name, payload.values, creating=True)
            async with self._session_factory.begin() as session:
                record = (
                    Faq(**values, is_test=True)
                    if table_name == "faq"
                    else self._models[table_name](**values)
                )
                session.add(record)
                await session.flush()
                if isinstance(record, Faq):
                    await sync_faq_record(session, record)
                await session.refresh(record)
                return _to_record(record)
        except ValidationError as exc:
            raise TableRecordValidationError("仅允许符合测试记录规则的字段和取值") from exc
        except IntegrityError as exc:
            raise TableRecordConflictError("主键重复或关联的测试会话不存在") from exc

    async def update(
        self,
        table_name: DatabaseTableName,
        record_key: str,
        payload: TableRecordWrite,
    ) -> TableRecord:
        try:
            values = self._validate(table_name, payload.values, creating=False)
            async with self._session_factory.begin() as session:
                record = await session.get(
                    self._models[table_name],
                    self._key(table_name, record_key),
                )
                if record is None:
                    raise TableRecordNotFoundError(record_key)
                if not _can_update(record):
                    raise TableRecordReadOnlyError(record_key)
                self._apply_update(table_name, record, values)
                await session.flush()
                if isinstance(record, Faq):
                    await sync_faq_record(session, record)
                return _to_record(record)
        except ValidationError as exc:
            raise TableRecordValidationError("仅允许符合测试记录规则的字段和取值") from exc
        except IntegrityError as exc:
            raise TableRecordConflictError("关联的测试会话不存在或数据冲突") from exc

    async def delete(self, table_name: DatabaseTableName, record_key: str) -> None:
        try:
            async with self._session_factory.begin() as session:
                key = self._key(table_name, record_key)
                record = await session.get(self._models[table_name], key)
                if record is None:
                    raise TableRecordNotFoundError(record_key)
                if not _is_test_record(record):
                    raise TableRecordReadOnlyError(record_key)
                if table_name == "conversations":
                    await session.execute(delete(Ticket).where(Ticket.conversation_id == key))
                    await session.execute(delete(Message).where(Message.conversation_id == key))
                if isinstance(record, Faq):
                    await deactivate_faq_knowledge(session, record.id)
                await session.delete(record)
                await session.flush()
        except IntegrityError as exc:
            raise TableRecordConflictError("测试记录仍被其他数据关联") from exc

    @staticmethod
    def _key(table_name: DatabaseTableName, raw_key: str) -> int | str:
        if table_name in {"faq", "messages"}:
            try:
                return int(raw_key)
            except ValueError as exc:
                raise TableRecordNotFoundError(raw_key) from exc
        return raw_key

    @staticmethod
    def _validate(
        table_name: DatabaseTableName,
        values: dict[str, Any],
        *,
        creating: bool,
    ) -> dict[str, Any]:
        schema: type[_StrictInput]
        if table_name == "faq":
            schema = _FaqInput
        elif table_name == "conversations":
            schema = _ConversationCreate if creating else _ConversationUpdate
        elif table_name == "messages":
            schema = _MessageInput
        else:
            schema = _TicketCreate if creating else _TicketUpdate
        return schema.model_validate(values).model_dump()

    @staticmethod
    def _apply_update(
        table_name: DatabaseTableName,
        record: Any,
        values: dict[str, Any],
    ) -> None:
        allowed = {
            "faq": ("question", "answer", "category"),
            "conversations": ("user_id", "status"),
            "messages": ("conversation_id", "role", "content", "tool_calls", "tool_call_id"),
            "tickets": (
                "conversation_id",
                "issue_description",
                "ticket_type",
                "status",
            ),
        }[table_name]
        for field in allowed:
            setattr(record, field, values[field])
