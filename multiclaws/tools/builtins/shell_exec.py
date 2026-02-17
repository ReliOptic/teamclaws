"""Sandboxed subprocess, 5s timeout. (§7-2)"""
from __future__ import annotations

import shlex

from multiclaws.tools.registry import Tool
from multiclaws.tools.sandbox import run_subprocess


class ShellExecTool(Tool):
    name = "shell_exec"
    description = "Execute a shell command inside the workspace sandbox (5s timeout, no network)."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "cwd": {"type": "string", "description": "Working dir (relative to workspace)"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (max 30)"},
        },
        "required": ["command"],
    }

    async def execute(self, command: str, cwd: str | None = None,
                      timeout: int = 5, **_) -> dict:
        timeout = min(timeout, 30)
        try:
            cmd = shlex.split(command)
        except ValueError as e:
            return {"error": f"Invalid command: {e}"}
        return await run_subprocess(cmd, timeout=timeout, cwd=cwd)
