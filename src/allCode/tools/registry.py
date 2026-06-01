"""Tool registry with provider schema generation."""

from __future__ import annotations

from collections.abc import Iterable

from allCode.tools.base import BaseTool, ToolDefinition, tool_schema


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._aliases: dict[str, str] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        name = self.normalize_name(tool.definition.name)
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = tool
        for alias in tool.definition.aliases:
            normalized_alias = self.normalize_name(alias)
            if normalized_alias in self._tools or normalized_alias in self._aliases:
                raise ValueError(f"tool alias already registered: {alias}")
            self._aliases[normalized_alias] = name

    def get(self, name: str) -> BaseTool | None:
        normalized = self.normalize_name(name)
        canonical = self._aliases.get(normalized, normalized)
        return self._tools.get(canonical)

    def require(self, name: str) -> BaseTool:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"tool not registered: {name}")
        return tool

    def definitions(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    def group(self, group_name: str) -> list[ToolDefinition]:
        normalized = group_name.strip().lower()
        return [definition for definition in self.definitions() if definition.group == normalized]

    def provider_schemas(self) -> list[dict[str, object]]:
        return [tool_schema(tool.definition) for tool in self._tools.values()]

    def names(self) -> set[str]:
        return set(self._tools)

    @staticmethod
    def normalize_name(name: str) -> str:
        return name.strip().lower().replace("-", "_")
