from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Message, MessageRole
from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository
from app.schemas import (
    ConversationHistory,
    ConversationHistoryMessage,
    ConversationSummary,
)


class ConversationHistoryNotFoundError(LookupError):
    pass


def records_to_history_messages(
    records: list[Message],
) -> list[ConversationHistoryMessage]:
    visible: list[ConversationHistoryMessage] = []
    pending_tool_name: str | None = None

    for record in records:
        if record.role is MessageRole.USER:
            pending_tool_name = None
            content = record.content.strip()
            if content:
                visible.append(
                    ConversationHistoryMessage(
                        role="user",
                        content=content,
                    )
                )
            continue

        if record.role is MessageRole.TOOL:
            continue

        if record.tool_calls:
            first_call = record.tool_calls[0]
            name = first_call.get("name")
            pending_tool_name = name if isinstance(name, str) and name else None
            continue

        content = record.content.strip()
        if not content:
            continue
        visible.append(
            ConversationHistoryMessage(
                role="assistant",
                content=content,
                tool_name=pending_tool_name,
            )
        )
        pending_tool_name = None

    return visible


class ConversationHistoryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_conversations(self, user_id: str) -> list[ConversationSummary]:
        async with self._session_factory() as session:
            records = await ConversationRepository(session).list_for_user(user_id)
        return [
            ConversationSummary(
                id=record.conversation.id,
                status=record.conversation.status.value,
                created_at=record.conversation.created_at,
                last_message_at=record.last_message_at,
                preview=record.preview[:80],
                message_count=record.message_count,
            )
            for record in records
        ]

    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
    ) -> ConversationHistory:
        async with self._session_factory() as session:
            conversation = await ConversationRepository(session).get_for_user(
                conversation_id,
                user_id,
            )
            if conversation is None:
                raise ConversationHistoryNotFoundError(conversation_id)
            records = await MessageRepository(session).list_for_conversation(conversation_id)
        return ConversationHistory(
            conversation_id=conversation_id,
            messages=records_to_history_messages(records),
        )
