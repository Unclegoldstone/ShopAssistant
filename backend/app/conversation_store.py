from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately


class InputTooLongError(ValueError):
    """Raised when the current user message alone exceeds the token budget."""


class ConversationStore:
    """Single-process conversation history with per-conversation serialization."""

    def __init__(self) -> None:
        self._histories: dict[str, list[BaseMessage]] = {}
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._state_lock = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, conversation_id: str) -> AsyncIterator[None]:
        conversation_lock = self._conversation_locks.setdefault(conversation_id, asyncio.Lock())
        async with conversation_lock:
            yield

    async def get_history(self, conversation_id: str) -> list[BaseMessage]:
        async with self._state_lock:
            return list(self._histories.get(conversation_id, []))

    async def commit_turn(self, conversation_id: str, user_input: str, answer: str) -> None:
        async with self._state_lock:
            history = self._histories.setdefault(conversation_id, [])
            history.extend(
                [
                    HumanMessage(content=user_input),
                    AIMessage(content=answer),
                ]
            )

    async def clear(self, conversation_id: str) -> None:
        async with self._state_lock:
            self._histories.pop(conversation_id, None)

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

        return trim_messages(
            history,
            max_tokens=history_budget,
            token_counter="approximate",
            strategy="last",
            start_on="human",
            allow_partial=False,
        )

