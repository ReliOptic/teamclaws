"""Tests for multiclaws.tools — ToolRegistry + builtin tools."""
import pytest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ── ToolRegistry ─────────────────────────────────────────────────────────────

class TestToolRegistry:
    def test_register_and_get(self):
        from multiclaws.tools.registry import ToolRegistry
        from multiclaws.tools.builtins.file_ops import FileReadTool
        reg = ToolRegistry()
        tool = FileReadTool()
        reg.register(tool)
        assert reg.get("file_read") is tool

    def test_all_names(self):
        from multiclaws.tools.registry import ToolRegistry
        from multiclaws.tools.builtins.file_ops import FileReadTool, FileWriteTool
        reg = ToolRegistry()
        reg.register(FileReadTool())
        reg.register(FileWriteTool())
        assert "file_read" in reg.all_names()
        assert "file_write" in reg.all_names()

    def test_schemas_for_filtered(self):
        from multiclaws.tools.registry import ToolRegistry
        from multiclaws.tools.builtins.file_ops import FileReadTool, FileWriteTool
        reg = ToolRegistry()
        reg.register(FileReadTool())
        reg.register(FileWriteTool())
        schemas = reg.schemas_for(["file_read"])
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "file_read"

    def test_schemas_for_empty_allowed(self):
        from multiclaws.tools.registry import ToolRegistry
        from multiclaws.tools.builtins.file_ops import FileReadTool
        reg = ToolRegistry()
        reg.register(FileReadTool())
        schemas = reg.schemas_for([])
        assert schemas == []

    @pytest.mark.asyncio
    async def test_execute_allowed(self, workspace):
        from multiclaws.tools.registry import ToolRegistry
        from multiclaws.tools.builtins.file_ops import FileWriteTool
        with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
            reg = ToolRegistry()
            reg.register(FileWriteTool())
            result = await reg.execute(
                "file_write", {"path": "t.txt", "content": "hi"},
                "coder", ["file_write"], audit_fn=None,
            )
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_execute_denied(self):
        from multiclaws.tools.registry import ToolRegistry
        from multiclaws.tools.builtins.file_ops import FileWriteTool
        reg = ToolRegistry()
        reg.register(FileWriteTool())
        result = await reg.execute(
            "file_write", {"path": "t.txt", "content": "hi"},
            "researcher", ["file_read"],  # researcher not allowed file_write
            audit_fn=None,
        )
        assert "error" in result
        assert "not permitted" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self):
        from multiclaws.tools.registry import ToolRegistry
        reg = ToolRegistry()
        result = await reg.execute(
            "nonexistent", {}, "ceo", ["nonexistent"], audit_fn=None
        )
        assert "not found" in result["error"]

    def test_get_registry_singleton(self):
        from multiclaws.tools.registry import get_registry
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


# ── FileReadTool ─────────────────────────────────────────────────────────────

class TestFileReadTool:
    @pytest.mark.asyncio
    async def test_read_existing_file(self, workspace):
        from multiclaws.tools.builtins.file_ops import FileReadTool
        (workspace / "hello.txt").write_text("hello world")
        with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
            result = await FileReadTool().execute(path="hello.txt")
        assert result.get("content") == "hello world"

    @pytest.mark.asyncio
    async def test_read_nonexistent_returns_error(self, workspace):
        from multiclaws.tools.builtins.file_ops import FileReadTool
        with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
            result = await FileReadTool().execute(path="missing.txt")
        assert "error" in result


# ── FileWriteTool ────────────────────────────────────────────────────────────

class TestFileWriteTool:
    @pytest.mark.asyncio
    async def test_write_creates_file(self, workspace):
        from multiclaws.tools.builtins.file_ops import FileWriteTool
        with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
            result = await FileWriteTool().execute(path="out.txt", content="data")
        assert "error" not in result
        assert (workspace / "out.txt").read_text() == "data"

    @pytest.mark.asyncio
    async def test_write_escape_blocked(self, workspace):
        from multiclaws.tools.builtins.file_ops import FileWriteTool
        with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
            result = await FileWriteTool().execute(path="../../evil.txt", content="x")
        assert "error" in result


# ── FileListTool ─────────────────────────────────────────────────────────────

class TestFileListTool:
    @pytest.mark.asyncio
    async def test_list_files(self, workspace):
        from multiclaws.tools.builtins.file_ops import FileListTool
        (workspace / "a.txt").write_text("a")
        (workspace / "b.txt").write_text("b")
        with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
            result = await FileListTool().execute(path=".")
        content = result.get("files") or result.get("content") or str(result)
        assert "a.txt" in content or "a.txt" in str(result)

    @pytest.mark.asyncio
    async def test_list_nonexistent_returns_error(self, workspace):
        from multiclaws.tools.builtins.file_ops import FileListTool
        with patch("multiclaws.tools.sandbox.WORKSPACE", workspace):
            result = await FileListTool().execute(path="nodir")
        assert "error" in result


# ── WebFetchTool ─────────────────────────────────────────────────────────────

class TestWebFetchTool:
    def test_tool_name(self):
        from multiclaws.tools.builtins.web_fetch import WebFetchTool
        assert WebFetchTool().name == "web_fetch"

    def test_tool_has_parameters(self):
        from multiclaws.tools.builtins.web_fetch import WebFetchTool
        schema = WebFetchTool().to_schema()
        assert "url" in schema["function"]["parameters"]["properties"]


# ── Permissions ──────────────────────────────────────────────────────────────

class TestPermissions:
    def test_ceo_has_delegate_task(self):
        from multiclaws.roles.permissions import get_tools_for_role
        tools = get_tools_for_role("ceo")
        assert "delegate_task" in tools

    def test_researcher_has_web_fetch(self):
        from multiclaws.roles.permissions import get_tools_for_role
        tools = get_tools_for_role("researcher")
        assert "web_fetch" in tools

    def test_researcher_no_file_write(self):
        from multiclaws.roles.permissions import get_tools_for_role
        tools = get_tools_for_role("researcher")
        assert "file_write" not in tools

    def test_coder_has_shell_exec(self):
        from multiclaws.roles.permissions import get_tools_for_role
        tools = get_tools_for_role("coder")
        assert "shell_exec" in tools

    def test_preset_inherits_base_role(self):
        from multiclaws.roles.permissions import get_tools_for_role
        # code-reviewer inherits from coder
        tools = get_tools_for_role("code-reviewer")
        assert "file_read" in tools

    def test_unknown_role_returns_empty(self):
        from multiclaws.roles.permissions import get_tools_for_role
        assert get_tools_for_role("nonexistent_role") == []
