from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage

from app.conversation_store import (
    ConversationAccessError,
    ConversationStore,
    InputTooLongError,
)
from app.models import ConversationStatus, MessageRole
from app.prompts import chat_prompt
from app.sse import done_event, error_event, openai_chunk_event
from app.tools.executor import ToolExecutionContext, ToolExecutor
from app.tools.registry import ToolRegistry, UnknownToolError

logger = logging.getLogger(__name__)


class ChatPreparationError(RuntimeError):
    """Raised when the pre-stream model decision cannot be completed."""


@dataclass(slots=True)
class PreparedTurn:
    conversation_id: str
    user_id: str
    messages: list[BaseMessage]
    tool_name: str | None
    lock: asyncio.Lock


class ChatService:
    def __init__(
        self,
        model: Any,
        store: ConversationStore,
        *,
        registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        model_name: str,
        history_max_tokens: int,
    ) -> None:
        self._model = model
        self._store = store
        self._registry = registry or ToolRegistry([])
        self._tool_executor = tool_executor or ToolExecutor(
            self._registry,
            timeout_seconds=5,
            max_attempts=2,
        )
        self._decision_model = model.bind_tools(
            self._registry.tools,
            tool_choice="auto",
            parallel_tool_calls=False,
        )
        self._model_name = model_name
        self._history_max_tokens = history_max_tokens

    async def validate_input(self, conversation_id: str, user_input: str) -> None:
        await self._store.history_for_request(
            conversation_id,
            user_input,
            max_tokens=self._history_max_tokens,
        )

    async def prepare_turn(
        self,
        conversation_id: str,
        user_input: str,
        *,
        user_id: str,
    ) -> PreparedTurn:
        conversation_lock = await self._store.acquire(conversation_id)
        user_persisted = False
        try:
            await self._store.assert_owner(conversation_id, user_id)
            history = await self._store.history_for_request(
                conversation_id,
                user_input,
                max_tokens=self._history_max_tokens,
            )
            await self._store.append_message(
                conversation_id,
                user_id=user_id,
                role=MessageRole.USER,
                content=user_input,
            )
            user_persisted = True
            messages = chat_prompt.format_messages(history=history, user_input=user_input)
            decision = await self._decision_model.ainvoke(messages)
            tool_calls = list(getattr(decision, "tool_calls", []) or [])

            if not tool_calls:
                return PreparedTurn(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    messages=messages,
                    tool_name=None,
                    lock=conversation_lock,
                )

            selected_call = tool_calls[0]
            assistant_tool_message = AIMessage(content="", tool_calls=[selected_call])
            tool_message = await self._tool_executor.execute(
                selected_call,
                context=ToolExecutionContext(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    tool_call_id=selected_call["id"],
                ),
            )
            await self._store.append_tool_exchange(
                conversation_id,
                user_id=user_id,
                tool_calls=[selected_call],
                tool_content=str(tool_message.content),
                tool_call_id=tool_message.tool_call_id,
            )
            try:
                self._registry.get(selected_call["name"])
                response_tool_name = selected_call["name"]
            except UnknownToolError:
                response_tool_name = None
            return PreparedTurn(
                conversation_id=conversation_id,
                user_id=user_id,
                messages=[*messages, assistant_tool_message, tool_message],
                tool_name=response_tool_name,
                lock=conversation_lock,
            )
        except (ConversationAccessError, InputTooLongError):
            conversation_lock.release()
            raise
        except Exception as exc:
            if user_persisted:
                await self._mark_failed(conversation_id)
            conversation_lock.release()
            logger.error(
                "chat preparation failed conversation_id=%s error_type=%s",
                conversation_id,
                type(exc).__name__,
            )
            raise ChatPreparationError("客服暂时无法处理该请求") from exc

    async def stream_prepared(self, prepared: PreparedTurn) -> AsyncIterator[str]:
        completion_id = f"chatcmpl-{uuid4().hex}"
        created = int(time.time())
        answer_parts: list[str] = []

        try:
            yield openai_chunk_event(
                completion_id=completion_id,
                created=created,
                model=self._model_name,
                delta={"role": "assistant"},
            )

            async for chunk in self._model.astream(prepared.messages):
                text = chunk.text
                if not text:
                    continue
                answer_parts.append(text)
                yield openai_chunk_event(
                    completion_id=completion_id,
                    created=created,
                    model=self._model_name,
                    delta={"content": text},
                )

            await self._store.append_message(
                prepared.conversation_id,
                user_id=prepared.user_id,
                role=MessageRole.ASSISTANT,
                content="".join(answer_parts),
            )
            yield openai_chunk_event(
                completion_id=completion_id,
                created=created,
                model=self._model_name,
                delta={},
                finish_reason="stop",
            )
            yield done_event()
        except asyncio.CancelledError:
            await self._persist_partial_failure(prepared, answer_parts)
            raise
        except Exception as exc:
            logger.error(
                "model stream failed conversation_id=%s error_type=%s",
                prepared.conversation_id,
                type(exc).__name__,
            )
            await self._persist_partial_failure(prepared, answer_parts)
            yield error_event()
            yield done_event()
        finally:
            prepared.lock.release()

    async def stream(
        self,
        conversation_id: str,
        user_input: str,
        *,
        user_id: str = "demo-user",
    ) -> AsyncIterator[str]:
        prepared = await self.prepare_turn(
            conversation_id,
            user_input,
            user_id=user_id,
        )
        async for event in self.stream_prepared(prepared):
            yield event

    async def _persist_partial_failure(
        self,
        prepared: PreparedTurn,
        answer_parts: list[str],
    ) -> None:
        if answer_parts:
            await self._store.append_message(
                prepared.conversation_id,
                user_id=prepared.user_id,
                role=MessageRole.ASSISTANT,
                content="".join(answer_parts),
            )
        await self._mark_failed(prepared.conversation_id)

    async def _mark_failed(self, conversation_id: str) -> None:
        try:
            await self._store.set_status(conversation_id, ConversationStatus.FAILED)
        except Exception as exc:
            logger.error(
                "failed to update conversation status conversation_id=%s error_type=%s",
                conversation_id,
                type(exc).__name__,
            )
