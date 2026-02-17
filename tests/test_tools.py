"""Tests for the tool system."""

import os

import pytest
import pytest_asyncio

from teamclaws.tools.sandbox import init_sandbox
from teamclaws.tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool, DeleteFileTool
from teamclaws.tools.math_tools import AddNumbersTool
from teamclaws.tools.base import ToolRegistry


@pytest.fixture(autouse=True)
def setup_workspace(tmp_path):
    """Set up a temp workspace for file tool tests."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_sandbox(str(workspace))
    yield workspace


class TestListFiles:
    """Tests for ListFilesTool."""

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, setup_workspace):
        tool = ListFilesTool()
        result = await tool.execute({"path": "."})
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_list_with_files(self, setup_workspace):
        (setup_workspace / "test.txt").write_text("hello")
        (setup_workspace / "subdir").mkdir()
        tool = ListFilesTool()
        result = await tool.execute({"path": "."})
        assert "test.txt" in result
        assert "[DIR]" in result
        assert "[FILE]" in result

    @pytest.mark.asyncio
    async def test_list_nonexistent_path(self, setup_workspace):
        tool = ListFilesTool()
        result = await tool.execute({"path": "nonexistent"})
        assert "Error" in result


class TestReadFile:
    """Tests for ReadFileTool."""

    @pytest.mark.asyncio
    async def test_read_file(self, setup_workspace):
        (setup_workspace / "test.txt").write_text("hello world")
        tool = ReadFileTool()
        result = await tool.execute({"path": "test.txt"})
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, setup_workspace):
        tool = ReadFileTool()
        result = await tool.execute({"path": "missing.txt"})
        assert "Error" in result


class TestWriteFile:
    """Tests for WriteFileTool."""

    @pytest.mark.asyncio
    async def test_write_file(self, setup_workspace):
        tool = WriteFileTool()
        result = await tool.execute({"path": "output.txt", "content": "test content"})
        assert "Successfully" in result
        assert (setup_workspace / "output.txt").read_text() == "test content"

    @pytest.mark.asyncio
    async def test_write_creates_subdirs(self, setup_workspace):
        tool = WriteFileTool()
        result = await tool.execute({"path": "sub/dir/file.txt", "content": "deep"})
        assert "Successfully" in result
        assert (setup_workspace / "sub" / "dir" / "file.txt").read_text() == "deep"


class TestDeleteFile:
    """Tests for DeleteFileTool."""

    @pytest.mark.asyncio
    async def test_delete_file(self, setup_workspace):
        filepath = setup_workspace / "deleteme.txt"
        filepath.write_text("bye")
        tool = DeleteFileTool()
        result = await tool.execute({"path": "deleteme.txt"})
        assert "Successfully" in result
        assert not filepath.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, setup_workspace):
        tool = DeleteFileTool()
        result = await tool.execute({"path": "nope.txt"})
        assert "Error" in result


class TestAddNumbers:
    """Tests for AddNumbersTool."""

    @pytest.mark.asyncio
    async def test_add_integers(self):
        tool = AddNumbersTool()
        result = await tool.execute({"a": 3, "b": 5})
        assert result == "8"

    @pytest.mark.asyncio
    async def test_add_floats(self):
        tool = AddNumbersTool()
        result = await tool.execute({"a": 1.5, "b": 2.5})
        assert result == "4.0"

    @pytest.mark.asyncio
    async def test_add_negative(self):
        tool = AddNumbersTool()
        result = await tool.execute({"a": -10, "b": 3})
        assert result == "-7"


class TestToolRegistry:
    """Tests for the tool registry."""

    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = AddNumbersTool()
        registry.register(tool)
        assert registry.get("add_numbers") is tool

    def test_list_tools(self):
        registry = ToolRegistry()
        registry.register(AddNumbersTool())
        registry.register(ListFilesTool())
        names = registry.list_tools()
        assert "add_numbers" in names
        assert "list_files" in names

    def test_get_schemas_filtered(self):
        registry = ToolRegistry()
        registry.register(AddNumbersTool())
        registry.register(ListFilesTool())
        schemas = registry.get_schemas(allowed_tools=["add_numbers"])
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "add_numbers"
