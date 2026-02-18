"""
DelegateTaskTool — CEO delegates tasks to sub-agents inline.
Dispatcher is injected at CEOAgent.run() time; None by default (returns error).
"""
from __future__ import annotations

from typing import Any, Callable, Coroutine

from multiclaws.tools.registry import Tool


class DelegateTaskTool(Tool):
    name = "delegate_task"
    description = (
        "Delegate a task to a specialist agent. "
        "Use agent='researcher' for web research, 'coder' for code/files, "
        "'communicator' for message drafting."
    )
    parameters = {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "enum": ["researcher", "coder", "communicator"],
                "description": "Target agent role",
            },
            "task": {
                "type": "object",
                "description": "Task payload. Include 'message' or role-specific keys.",
            },
        },
        "required": ["agent", "task"],
    }

    def __init__(self) -> None:
        # Dispatcher set externally by CEOAgent after initialization
        self._dispatcher: Callable[..., Coroutine[Any, Any, dict]] | None = None

    async def execute(self, agent: str, task: dict, **_: Any) -> dict:
        if self._dispatcher is None:
            return {"error": "DelegateTaskTool has no dispatcher. Set _dispatcher in CEOAgent."}
        try:
            return await self._dispatcher(agent, task)
        except Exception as exc:
            return {"error": f"Delegation to '{agent}' failed: {exc}"}
