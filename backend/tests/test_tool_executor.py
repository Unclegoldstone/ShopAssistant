from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from app.tools.executor import ToolExecutionContext, ToolExecutor
from app.tools.registry import ToolRegistry


class ValueArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1)


@tool(args_schema=ValueArgs)
async def echo(value: str) -> dict[str, str]:
    """Echo one value."""
    return {"value": value}


@pytest.mark.asyncio
async def test_executor_returns_json_tool_message_and_validates_arguments() -> None:
    executor = ToolExecutor(ToolRegistry([echo]), timeout_seconds=1, max_attempts=2)
    context = ToolExecutionContext("c1", "demo-user", "call-1")

    success = await executor.execute(
        {"name": "echo", "args": {"value": "ok"}, "id": "call-1"},
        context=context,
    )
    invalid = await executor.execute(
        {"name": "echo", "args": {"value": "", "extra": "x"}, "id": "call-2"},
        context=context,
    )
    unknown = await executor.execute(
        {"name": "missing", "args": {}, "id": "call-3"},
        context=context,
    )

    assert success.tool_call_id == "call-1"
    assert json.loads(success.content) == {"ok": True, "data": {"value": "ok"}}
    assert json.loads(invalid.content)["error"]["code"] == "invalid_arguments"
    assert json.loads(unknown.content)["error"]["code"] == "unknown_tool"


@pytest.mark.asyncio
async def test_executor_retries_timeout_once_and_sanitizes_final_error() -> None:
    attempts = 0

    @tool(args_schema=ValueArgs)
    async def slow(value: str) -> dict[str, str]:
        """Always exceed the execution deadline."""
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.05)
        return {"value": value, "secret": "must-not-leak"}

    executor = ToolExecutor(ToolRegistry([slow]), timeout_seconds=0.001, max_attempts=2)
    result = await executor.execute(
        {"name": "slow", "args": {"value": "x"}, "id": "call-slow"},
        context=ToolExecutionContext("c1", "demo-user", "call-slow"),
    )

    payload = json.loads(result.content)
    assert attempts == 2
    assert payload["error"]["code"] == "timeout"
    assert "must-not-leak" not in result.content
