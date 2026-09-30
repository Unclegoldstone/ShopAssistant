from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage


class FakeStructuredRunnable:
    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> object:
        self.calls.append(list(messages))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeBoundToolsModel:
    def __init__(self, responses: list[AIMessage | Exception] | None = None) -> None:
        self._responses = iter(responses) if responses is not None else None
        self.calls: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        self.calls.append(list(messages))
        if self._responses is None:
            return AIMessage(content="")
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


class FakeStreamingModel:
    def __init__(
        self,
        responses: list[list[str] | Exception],
        *,
        structured_response: object | None = None,
        decision_responses: list[AIMessage | Exception] | None = None,
    ) -> None:
        self._responses = iter(responses)
        self.calls: list[list[BaseMessage]] = []
        self.structured_calls: list[tuple[object, str, bool]] = []
        self.structured_runnable = FakeStructuredRunnable(structured_response or {})
        self.bound_tools_calls: list[tuple[list[object], str, bool]] = []
        self.bound_tools_model = FakeBoundToolsModel(decision_responses)

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

    def bind_tools(
        self,
        tools: list[object],
        *,
        tool_choice: str,
        parallel_tool_calls: bool,
    ) -> FakeBoundToolsModel:
        self.bound_tools_calls.append((tools, tool_choice, parallel_tool_calls))
        return self.bound_tools_model
