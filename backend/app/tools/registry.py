from __future__ import annotations

from collections.abc import Iterable

from langchain_core.tools import BaseTool


class DuplicateToolError(ValueError):
    pass


class UnknownToolError(LookupError):
    pass


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool]) -> None:
        self._tools: dict[str, BaseTool] = {}
        for registered_tool in tools:
            if registered_tool.name in self._tools:
                raise DuplicateToolError(f"工具名称重复：{registered_tool.name}")
            self._tools[registered_tool.name] = registered_tool

    @property
    def tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"未知工具：{name}") from exc
