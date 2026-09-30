from __future__ import annotations

import pytest
from langchain_core.tools import tool

from app.tools.registry import DuplicateToolError, ToolRegistry, UnknownToolError


@tool
def sample_tool(value: str) -> str:
    """Return the supplied value."""
    return value


def test_registry_lists_gets_and_rejects_unknown_tools() -> None:
    registry = ToolRegistry([sample_tool])

    assert registry.tools == [sample_tool]
    assert registry.get("sample_tool") is sample_tool
    with pytest.raises(UnknownToolError):
        registry.get("missing")


def test_registry_rejects_duplicate_names() -> None:
    with pytest.raises(DuplicateToolError):
        ToolRegistry([sample_tool, sample_tool])
