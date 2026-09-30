from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ConversationStatus, Message, MessageRole
from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository


class InputTooLongError(ValueError):
    """Raised when the current user message alone exceeds the token budget."""


class ConversationAccessError(PermissionError):
    """Raised before history is read when a conversation belongs to another user."""


def message_record_to_langchain(message: Message) -> BaseMessage:
    if message.role is MessageRole.USER:
        return HumanMessage(content=message.content)
    if message.role is MessageRole.TOOL:
        return ToolMessage(
            content=message.content,
            tool_call_id=message.tool_call_id or "",
        )
    return AIMessage(content=message.content, tool_calls=message.tool_calls or [])


def keep_recent_complete_turns(
    history: list[BaseMessage],
    *,
    max_tokens: int,
) -> list[BaseMessage]:
    turns: list[list[BaseMessage]] = []
    for message in history:
        if isinstance(message, HumanMessage):
            turns.append([message])
        elif turns:
            turns[-1].append(message)

    selected: list[list[BaseMessage]] = []
    for turn in reversed(turns):
        candidate = turn + [message for selected_turn in selected for message in selected_turn]
        if count_tokens_approximately(candidate) > max_tokens:
            break
        selected.insert(0, turn)

    return [message for turn in selected for message in turn]


class ConversationStore:
    """Conversation history backed by MySQL, with an in-memory test adapter."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._histories: dict[str, list[BaseMessage]] = {}
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._state_lock = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, conversation_id: str) -> AsyncIterator[None]:
        conversation_lock = self._conversation_locks.setdefault(conversation_id, asyncio.Lock())
        async with conversation_lock:
            yield

    async def acquire(self, conversation_id: str) -> asyncio.Lock:
        conversation_lock = self._conversation_locks.setdefault(conversation_id, asyncio.Lock())
        await conversation_lock.acquire()
        return conversation_lock

    async def get_history(self, conversation_id: str) -> list[BaseMessage]:
        if self._session_factory is None:
            async with self._state_lock:
                return list(self._histories.get(conversation_id, []))

        async with self._session_factory() as session:
            records = await MessageRepository(session).list_for_conversation(conversation_id)
        return [message_record_to_langchain(record) for record in records]

    async def assert_owner(self, conversation_id: str, user_id: str) -> None:
        if self._session_factory is None:
            return
        async with self._session_factory() as session:
            conversation = await ConversationRepository(session).get(conversation_id)
        if conversation is not None and conversation.user_id != user_id:
            raise ConversationAccessError(conversation_id)

    async def append_message(
        self,
        conversation_id: str,
        *,
        user_id: str,
        role: MessageRole,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        if self._session_factory is None:
            langchain_message: BaseMessage
            if role is MessageRole.USER:
                langchain_message = HumanMessage(content=content)
            elif role is MessageRole.TOOL:
                langchain_message = ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id or "",
                )
            else:
                langchain_message = AIMessage(content=content, tool_calls=tool_calls or [])
            async with self._state_lock:
                self._histories.setdefault(conversation_id, []).append(langchain_message)
            return

        async with self._session_factory.begin() as session:
            await ConversationRepository(session).get_or_create(conversation_id, user_id)
            await MessageRepository(session).add(
                conversation_id,
                role,
                content,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )

    async def append_tool_exchange(
        self,
        conversation_id: str,
        *,
        user_id: str,
        tool_calls: list[dict[str, Any]],
        tool_content: str,
        tool_call_id: str,
    ) -> None:
        if self._session_factory is None:
            async with self._state_lock:
                self._histories.setdefault(conversation_id, []).extend(
                    [
                        AIMessage(content="", tool_calls=tool_calls),
                        ToolMessage(content=tool_content, tool_call_id=tool_call_id),
                    ]
                )
            return

        async with self._session_factory.begin() as session:
            await ConversationRepository(session).get_or_create(conversation_id, user_id)
            messages = MessageRepository(session)
            await messages.add(
                conversation_id,
                MessageRole.ASSISTANT,
                "",
                tool_calls=tool_calls,
            )
            await messages.add(
                conversation_id,
                MessageRole.TOOL,
                tool_content,
                tool_call_id=tool_call_id,
            )

    async def commit_turn(
        self,
        conversation_id: str,
        user_input: str,
        answer: str,
        *,
        user_id: str = "demo-user",
    ) -> None:
        if self._session_factory is None:
            async with self._state_lock:
                history = self._histories.setdefault(conversation_id, [])
                history.extend(
                    [
                        HumanMessage(content=user_input),
                        AIMessage(content=answer),
                    ]
                )
            return

        async with self._session_factory.begin() as session:
            await ConversationRepository(session).get_or_create(conversation_id, user_id)
            messages = MessageRepository(session)
            await messages.add(conversation_id, MessageRole.USER, user_input)
            await messages.add(conversation_id, MessageRole.ASSISTANT, answer)

    async def clear(self, conversation_id: str) -> None:
        if self._session_factory is None:
            async with self._state_lock:
                self._histories.pop(conversation_id, None)
            return

        async with self._session_factory.begin() as session:
            await ConversationRepository(session).delete(conversation_id)

    async def set_status(
        self,
        conversation_id: str,
        status: ConversationStatus,
    ) -> None:
        if self._session_factory is None:
            return
        async with self._session_factory.begin() as session:
            await ConversationRepository(session).set_status(conversation_id, status)

    async def history_for_request(
        self,
        conversation_id: str,
        current_user_input: str,
        *,
        max_tokens: int,
    ) -> list[BaseMessage]:
        current_tokens = count_tokens_approximately([HumanMessage(content=current_user_input)])
        if current_tokens > max_tokens:
            raise InputTooLongError("当前消息超过上下文 token 预算")

        history = await self.get_history(conversation_id)
        history_budget = max_tokens - current_tokens
        if not history or history_budget <= 0:
            return []

        return keep_recent_complete_turns(history, max_tokens=history_budget)
