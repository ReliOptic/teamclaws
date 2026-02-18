"""
RunPythonTool — execute Python code in the sandbox workspace.
Writes code to workspace/_tc_run.py, runs with subprocess, returns stdout/stderr.
Timeout max 30s. stdout capped at 10KB by run_subprocess.
"""
from __future__ import annotations

import sys
from typing import Any

from multiclaws.tools.registry import Tool
from multiclaws.tools.sandbox import WORKSPACE, run_subprocess


class RunPythonTool(Tool):
    name = "run_python"
    description = (
        "Execute Python code in the workspace sandbox. "
        "Returns stdout, stderr, and returncode. "
        "Timeout default 10s, max 30s. No network access from sandboxed code."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Max execution seconds (default 10, max 30)",
                "default": 10,
            },
        },
        "required": ["code"],
    }

    async def execute(self, code: str, timeout: int = 10, **_: Any) -> dict:
        timeout = min(int(timeout), 30)
        script_path = WORKSPACE / "_tc_run.py"
        try:
            script_path.write_text(code, encoding="utf-8")
            result = await run_subprocess(
                [sys.executable, str(script_path)],
                timeout=timeout,
            )
            return result
        except Exception as exc:
            return {"returncode": -1, "stdout": "", "stderr": str(exc), "timed_out": False}
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except Exception:
                pass
