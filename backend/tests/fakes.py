from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from langchain_core.messages import AIMessageChunk, BaseMessage


class FakeStructuredRunnable:
    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> object:
        self.calls.append(list(messages))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeStreamingModel:
    def __init__(
        self,
        responses: list[list[str] | Exception],
        *,
        structured_response: object | None = None,
    ) -> None:
        self._responses = iter(responses)
        self.calls: list[list[BaseMessage]] = []
        self.structured_calls: list[tuple[object, str, bool]] = []
        self.structured_runnable = FakeStructuredRunnable(structured_response or {})

    async def astream(self, messages: Sequence[BaseMessage]) -> AsyncIterator[AIMessageChunk]:
        self.calls.append(list(messages))
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        for content in response:
            yield AIMessageChunk(content=content)

    def with_structured_output(
        self,
        schema: object,
        *,
        method: str,
        strict: bool,
    ) -> FakeStructuredRunnable:
        self.structured_calls.append((schema, method, strict))
        return self.structured_runnable
