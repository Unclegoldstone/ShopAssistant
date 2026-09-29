from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from app.conversation_store import ConversationStore
from app.prompts import chat_prompt
from app.sse import done_event, error_event, openai_chunk_event

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(
        self,
        model: Any,
        store: ConversationStore,
        *,
        model_name: str,
        history_max_tokens: int,
    ) -> None:
        self._model = model
        self._store = store
        self._model_name = model_name
        self._history_max_tokens = history_max_tokens

    async def validate_input(self, conversation_id: str, user_input: str) -> None:
        await self._store.history_for_request(
            conversation_id,
            user_input,
            max_tokens=self._history_max_tokens,
        )

    async def stream(self, conversation_id: str, user_input: str) -> AsyncIterator[str]:
        async with self._store.lock(conversation_id):
            history = await self._store.history_for_request(
                conversation_id,
                user_input,
                max_tokens=self._history_max_tokens,
            )
            messages = chat_prompt.format_messages(history=history, user_input=user_input)
            completion_id = f"chatcmpl-{uuid4().hex}"
            created = int(time.time())

            yield openai_chunk_event(
                completion_id=completion_id,
                created=created,
                model=self._model_name,
                delta={"role": "assistant"},
            )

            answer_parts: list[str] = []
            try:
                async for chunk in self._model.astream(messages):
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
            except Exception as exc:
                logger.error(
                    "model stream failed conversation_id=%s error_type=%s",
                    conversation_id,
                    type(exc).__name__,
                )
                yield error_event()
                yield done_event()
                return

            answer = "".join(answer_parts)
            await self._store.commit_turn(conversation_id, user_input, answer)
            yield openai_chunk_event(
                completion_id=completion_id,
                created=created,
                model=self._model_name,
                delta={},
                finish_reason="stop",
            )
            yield done_event()
