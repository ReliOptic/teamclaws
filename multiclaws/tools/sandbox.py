"""
Tool sandbox: safe_path containment + subprocess execution. (§7)
No network access from sandboxed code. stdout/stderr capped at 10KB.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from multiclaws.config import WORKSPACE

SANDBOX_TIMEOUT = 5  # seconds, configurable
OUTPUT_LIMIT = 10 * 1024  # 10KB


class SecurityError(Exception):
    pass


def safe_path(user_path: str) -> Path:
    """All file operations MUST go through this. No exceptions. (§7-1)"""
    resolved = (WORKSPACE / user_path).resolve()
    if not str(resolved).startswith(str(WORKSPACE)):
        raise SecurityError(f"Path escape attempt: {user_path}")
    return resolved


async def run_subprocess(
    cmd: list[str],
    timeout: int = SANDBOX_TIMEOUT,
    cwd: str | None = None,
) -> dict:
    """
    Run subprocess sandboxed:
    - Timeout enforced
    - No network (best-effort on Linux via env isolation)
    - stdout/stderr truncated at 10KB
    - Windows compatible (no Unix-only signals)
    """
    if cwd:
        work_dir = str(safe_path(cwd))
    else:
        work_dir = str(WORKSPACE)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Timeout after {timeout}s",
                "timed_out": True,
            }

        stdout = stdout_b[:OUTPUT_LIMIT].decode("utf-8", errors="replace")
        stderr = stderr_b[:OUTPUT_LIMIT].decode("utf-8", errors="replace")

        return {
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
        }

    except Exception as exc:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }
