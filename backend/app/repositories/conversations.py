from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, ConversationStatus, Message, MessageRole, Ticket


@dataclass(frozen=True, slots=True)
class ConversationSummaryRecord:
    conversation: Conversation
    last_message_at: datetime
    preview: str
    message_count: int


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, conversation_id: str) -> Conversation | None:
        return await self._session.get(Conversation, conversation_id)

    async def get_for_user(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        return await self._session.scalar(statement)

    async def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[ConversationSummaryRecord]:
        last_message_at = (
            select(func.max(Message.created_at))
            .where(Message.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        preview = (
            select(Message.content)
            .where(
                Message.conversation_id == Conversation.id,
                Message.role == MessageRole.USER,
                Message.content != "",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )
        visible_message_count = (
            select(func.count(Message.id))
            .where(
                Message.conversation_id == Conversation.id,
                or_(
                    Message.role == MessageRole.USER,
                    and_(
                        Message.role == MessageRole.ASSISTANT,
                        Message.content != "",
                    ),
                ),
            )
            .correlate(Conversation)
            .scalar_subquery()
        )
        activity_at = func.coalesce(last_message_at, Conversation.created_at)
        statement = (
            select(
                Conversation,
                activity_at.label("last_message_at"),
                func.coalesce(preview, "").label("preview"),
                visible_message_count.label("message_count"),
            )
            .where(Conversation.user_id == user_id)
            .order_by(activity_at.desc(), Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            ConversationSummaryRecord(
                conversation=row[0],
                last_message_at=row[1],
                preview=row[2],
                message_count=row[3],
            )
            for row in rows
        ]

    async def get_or_create(self, conversation_id: str, user_id: str) -> Conversation:
        conversation = await self.get(conversation_id)
        if conversation is not None:
            if conversation.user_id != user_id:
                raise ValueError("conversation_id 已属于其他用户")
            return conversation

        conversation = Conversation(id=conversation_id, user_id=user_id)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def set_status(
        self,
        conversation_id: str,
        status: ConversationStatus,
    ) -> Conversation:
        conversation = await self.get(conversation_id)
        if conversation is None:
            raise LookupError("会话不存在")
        conversation.status = status
        await self._session.flush()
        return conversation

    async def delete(self, conversation_id: str) -> None:
        await self._session.execute(delete(Ticket).where(Ticket.conversation_id == conversation_id))
        await self._session.execute(
            delete(Message).where(Message.conversation_id == conversation_id)
        )
        await self._session.execute(delete(Conversation).where(Conversation.id == conversation_id))
