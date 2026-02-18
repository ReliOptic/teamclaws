"""Tests for multiclaws.tools.sandbox — safe_path + run_subprocess."""
import pytest
from pathlib import Path
from unittest.mock import patch

import sys
import os
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def test_safe_path_within_workspace(workspace):
    from multiclaws.tools.sandbox import safe_path, SecurityError
    with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
        result = safe_path("subdir/file.txt")
        assert str(result).startswith(str(workspace))


def test_safe_path_dot_resolves_to_workspace(workspace):
    from multiclaws.tools.sandbox import safe_path, SecurityError
    with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
        result = safe_path(".")
        assert result.resolve() == workspace.resolve()


def test_safe_path_escape_double_dot_raises(workspace):
    from multiclaws.tools.sandbox import safe_path, SecurityError
    with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
        with pytest.raises(SecurityError):
            safe_path("../../etc/passwd")


def test_safe_path_escape_triple_dot_raises(workspace):
    from multiclaws.tools.sandbox import safe_path, SecurityError
    with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
        with pytest.raises(SecurityError):
            safe_path("../../../etc/shadow")


def test_safe_path_absolute_outside_raises(workspace):
    from multiclaws.tools.sandbox import safe_path, SecurityError
    with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
        with pytest.raises(SecurityError):
            safe_path("/etc/passwd")


@pytest.mark.asyncio
async def test_run_subprocess_success(workspace):
    from multiclaws.tools.sandbox import run_subprocess
    with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
        result = await run_subprocess(
            [sys.executable, "-c", "print('hello teamclaws')"], timeout=10
        )
    assert result["returncode"] == 0
    assert "hello teamclaws" in result["stdout"]
    assert result["timed_out"] is False


@pytest.mark.asyncio
async def test_run_subprocess_stderr(workspace):
    from multiclaws.tools.sandbox import run_subprocess
    with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
        result = await run_subprocess(
            [sys.executable, "-c", "import sys; sys.stderr.write('err')"], timeout=10
        )
    assert "err" in result["stderr"]


@pytest.mark.asyncio
async def test_run_subprocess_timeout(workspace):
    from multiclaws.tools.sandbox import run_subprocess
    with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
        result = await run_subprocess(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1
        )
    assert result["timed_out"] is True
    assert result["returncode"] == -1


@pytest.mark.asyncio
async def test_run_subprocess_nonzero_exit(workspace):
    from multiclaws.tools.sandbox import run_subprocess
    with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
        result = await run_subprocess(
            [sys.executable, "-c", "raise SystemExit(1)"], timeout=5
        )
    assert result["returncode"] == 1
    assert result["timed_out"] is False
