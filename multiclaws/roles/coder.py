"""Coder PicoClaw: file I/O + code execution. (§6-2)"""
from __future__ import annotations

import json
from typing import Any

from multiclaws.core.picoclaw import PicoClaw
from multiclaws.llm.router import LLMRouter
from multiclaws.roles.permissions import get_tools_for_role
from multiclaws.tools.registry import get_registry

CODER_SYSTEM = """You are a Coder agent. Your job is to write, modify, and execute code.
Use file_read/file_write for files. Use shell_exec or run_python to execute code.
Write production-ready code. No TODOs, no placeholders. Every file must be runnable.

To use a tool, respond with JSON only (no other text):
{"tool": "run_python", "args": {"code": "print('hello')"}}
{"tool": "file_write", "args": {"path": "script.py", "content": "..."}}
{"tool": "shell_exec", "args": {"command": "python script.py"}}

When done, respond with plain text (your final answer)."""


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

        registry = get_registry()
        tools = get_tools_for_role(self.role)
        content = ""

        for _ in range(self.config.max_tool_iterations):
            content = await self._router.complete(
                messages=messages,
                agent_role=self.role,
                task_type="complex",
            )
            messages.append({"role": "assistant", "content": content})

            if content.strip().startswith("{") and '"tool"' in content:
                try:
                    tool_call = json.loads(content)
                    tool_name = tool_call.get("tool", "")
                    tool_args = tool_call.get("args", {})
                    tool_result = await registry.execute(
                        tool_name, tool_args, self.role, tools,
                        audit_fn=self.store.audit if self.store else None,
                    )
                    messages.append({"role": "tool", "content": json.dumps(tool_result)})
                    continue
                except json.JSONDecodeError:
                    pass

            # Final answer (plain text)
            break

        return {"result": content, "instruction": instruction}
