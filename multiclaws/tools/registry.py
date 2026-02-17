"""
Tool ABC + ToolRegistry + JSON schema generation. (§4 Phase 4)
Tools register themselves; roles get filtered schema via permissions.
"""
from __future__ import annotations

import inspect
import json
from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Base class for all TeamClaws tools."""
    name: str = ""
    description: str = ""
    # JSON Schema for parameters
    parameters: dict = {}

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict:
        """Execute the tool. Returns dict with at least 'result' key."""

    def to_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas_for(self, allowed: list[str]) -> list[dict]:
        """Return OpenAI-format tool schemas filtered by allowed list."""
        return [
            t.to_schema()
            for name, t in self._tools.items()
            if name in allowed
        ]

    async def execute(self, name: str, kwargs: dict, agent_role: str,
                      allowed: list[str], audit_fn=None) -> dict:
        """Validate permission, log audit, execute."""
        if name not in allowed:
            if audit_fn:
                audit_fn(agent_role, name, kwargs, "denied", "not in allowed list")
            return {"error": f"Tool '{name}' not permitted for role '{agent_role}'"}

        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' not found"}

        if audit_fn:
            audit_fn(agent_role, name, kwargs, "allowed", "")

        try:
            return await tool.execute(**kwargs)
        except Exception as exc:
            if audit_fn:
                audit_fn(agent_role, name, kwargs, "error", str(exc))
            return {"error": str(exc)}


# ── Module-level singleton ─────────────────────────────────────────────────
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _load_builtins(_registry)
    return _registry


def _load_builtins(reg: ToolRegistry) -> None:
    from multiclaws.tools.builtins.file_ops import FileReadTool, FileWriteTool, FileListTool
    from multiclaws.tools.builtins.shell_exec import ShellExecTool
    from multiclaws.tools.builtins.web_fetch import WebFetchTool

    for tool in [FileReadTool(), FileWriteTool(), FileListTool(),
                 ShellExecTool(), WebFetchTool()]:
        reg.register(tool)
