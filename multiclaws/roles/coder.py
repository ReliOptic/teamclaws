"""Coder PicoClaw: file I/O + code execution. (§6-2)"""
from __future__ import annotations

from typing import Any

from multiclaws.core.picoclaw import PicoClaw
from multiclaws.llm.router import LLMRouter
from multiclaws.roles.permissions import get_tools_for_role
from multiclaws.tools.registry import get_registry

CODER_SYSTEM = """You are a Coder agent. Your job is to write, modify, and execute code.
Use file_read/file_write for files. Use shell_exec for running code (5s timeout).
Write production-ready code. No TODOs, no placeholders. Every file must be runnable."""


class CoderAgent(PicoClaw):
    role = "coder"
    description = "Code writing, file operations, and shell execution specialist"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._router: LLMRouter | None = None

    def run(self) -> None:
        self._router = LLMRouter(self.config)
        super().run()

    async def handle_task(self, task: dict[str, Any]) -> dict[str, Any]:
        instruction = task.get("instruction", task.get("message", ""))
        session_id = task.get("session_id", "coder:default")

        messages = [
            {"role": "system", "content": CODER_SYSTEM},
            {"role": "user", "content": instruction},
        ]

        content = await self._router.complete(
            messages=messages,
            agent_role=self.role,
            task_type="complex",
        )
        return {"result": content, "instruction": instruction}
