from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import Any

from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from app.tools.registry import ToolRegistry, UnknownToolError


class ToolNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    conversation_id: str
    user_id: str
    tool_call_id: str


_tool_execution_context: ContextVar[ToolExecutionContext | None] = ContextVar(
    "tool_execution_context",
    default=None,
)


def current_tool_execution_context() -> ToolExecutionContext:
    context = _tool_execution_context.get()
    if context is None:
        raise RuntimeError("工具执行上下文不可用")
    return context


def error_message(tool_call_id: str, code: str, message: str) -> ToolMessage:
    content = json.dumps(
        {"ok": False, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )
    return ToolMessage(content=content, tool_call_id=tool_call_id, status="error")


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        timeout_seconds: float,
        max_attempts: int,
    ) -> None:
        self._registry = registry
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts

    async def execute(
        self,
        tool_call: dict[str, Any],
        *,
        context: ToolExecutionContext,
    ) -> ToolMessage:
        tool_name = str(tool_call.get("name", ""))
        tool_call_id = str(tool_call.get("id", context.tool_call_id))
        arguments = tool_call.get("args", {})

        try:
            selected_tool = self._registry.get(tool_name)
        except UnknownToolError:
            return error_message(tool_call_id, "unknown_tool", "模型选择了不可用的工具")

        effective_context = replace(context, tool_call_id=tool_call_id)
        last_error_code = "execution_error"
        token: Token[ToolExecutionContext | None] | None = None

        for attempt in range(self._max_attempts):
            try:
                token = _tool_execution_context.set(effective_context)
                async with asyncio.timeout(self._timeout_seconds):
                    result = await selected_tool.ainvoke(arguments)
                content = json.dumps({"ok": True, "data": result}, ensure_ascii=False)
                return ToolMessage(content=content, tool_call_id=tool_call_id)
            except ValidationError:
                return error_message(tool_call_id, "invalid_arguments", "工具参数不符合要求")
            except ToolNotFoundError:
                return error_message(tool_call_id, "not_found", "未查询到相关信息")
            except TimeoutError:
                last_error_code = "timeout"
            except Exception:
                last_error_code = "execution_error"
            finally:
                if token is not None:
                    _tool_execution_context.reset(token)
                    token = None

            if attempt + 1 >= self._max_attempts:
                break

        if last_error_code == "timeout":
            return error_message(tool_call_id, "timeout", "工具执行超时，请稍后重试")
        return error_message(tool_call_id, "execution_error", "工具暂时不可用，请稍后重试")
