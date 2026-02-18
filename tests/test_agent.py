"""Tests for multiclaws agent system — permissions, registry, CEO React loop."""
import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Permissions matrix ────────────────────────────────────────────────────────

class TestPermissions:
    def test_ceo_tools(self):
        from multiclaws.roles.permissions import get_tools_for_role
        tools = get_tools_for_role("ceo")
        assert "file_read" in tools
        assert "file_write" in tools
        assert "web_fetch" in tools
        assert "delegate_task" in tools

    def test_researcher_tools(self):
        from multiclaws.roles.permissions import get_tools_for_role
        tools = get_tools_for_role("researcher")
        assert "web_fetch" in tools
        assert "file_read" in tools
        assert "file_write" not in tools
        assert "shell_exec" not in tools

    def test_coder_tools(self):
        from multiclaws.roles.permissions import get_tools_for_role
        tools = get_tools_for_role("coder")
        assert "shell_exec" in tools
        assert "file_write" in tools
        assert "web_fetch" in tools

    def test_communicator_tools(self):
        from multiclaws.roles.permissions import get_tools_for_role
        tools = get_tools_for_role("communicator")
        assert "file_read" in tools
        assert "shell_exec" not in tools

    def test_preset_inherits_from_base(self):
        from multiclaws.roles.permissions import get_tools_for_role
        coder_tools = get_tools_for_role("coder")
        reviewer_tools = get_tools_for_role("code-reviewer")
        # code-reviewer role_base = coder
        assert set(reviewer_tools) == set(coder_tools)

    def test_unknown_role_empty(self):
        from multiclaws.roles.permissions import get_tools_for_role
        assert get_tools_for_role("ghost_role") == []


# ── Tool Registry ─────────────────────────────────────────────────────────────

class TestToolRegistry:
    def test_builtin_tools_registered(self):
        from multiclaws.tools.registry import get_registry
        reg = get_registry()
        names = reg.all_names()
        assert "file_read" in names
        assert "file_write" in names
        assert "file_list" in names
        assert "shell_exec" in names
        assert "web_fetch" in names

    def test_delegate_task_registered(self):
        from multiclaws.tools.registry import get_registry
        reg = get_registry()
        assert reg.get("delegate_task") is not None

    def test_run_python_registered(self):
        from multiclaws.tools.registry import get_registry
        reg = get_registry()
        assert reg.get("run_python") is not None

    def test_tool_schema_structure(self):
        from multiclaws.tools.registry import get_registry
        reg = get_registry()
        schemas = reg.schemas_for(["file_read"])
        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]


# ── CEO handle_task — React loop ─────────────────────────────────────────────

class TestCEOHandleTask:
    @pytest.fixture
    def store(self, tmp_path):
        from multiclaws.memory.store import MemoryStore
        return MemoryStore(db_path=tmp_path / "test.db")

    @pytest.fixture
    def mock_router(self):
        from multiclaws.llm.provider import LLMResponse
        router = MagicMock()
        router.complete_full = AsyncMock(return_value=LLMResponse(
            content="Hello! I can help with that.",
            input_tokens=10,
            output_tokens=8,
            cost_usd=0.0001,
            latency_ms=100,
        ))
        return router

    @pytest.mark.asyncio
    async def test_handle_simple_task(self, store, mock_router):
        from multiclaws.roles.ceo import CEOAgent
        from multiclaws.config import get_config
        cfg = get_config()
        agent = CEOAgent(config=cfg)
        agent._store = store
        agent._router = mock_router
        agent._registry = MagicMock()
        agent._registry.schemas_for = MagicMock(return_value=[])
        agent._registry.execute = AsyncMock(return_value={"result": "done"})

        result = await agent.handle_task({
            "message": "What is Python?",
            "session_id": "test:session",
            "platform": "cli",
        })
        assert "result" in result
        assert result["result"] == "Hello! I can help with that."

    @pytest.mark.asyncio
    async def test_handle_empty_message(self, store, mock_router):
        from multiclaws.roles.ceo import CEOAgent
        from multiclaws.config import get_config
        cfg = get_config()
        agent = CEOAgent(config=cfg)
        agent._store = store
        agent._router = mock_router

        result = await agent.handle_task({"message": "", "session_id": "s1"})
        assert "result" in result
        assert "No message" in result["result"]

    @pytest.mark.asyncio
    async def test_react_loop_executes_tool_call(self, store):
        """CEO should detect JSON tool call and invoke registry.execute."""
        from multiclaws.roles.ceo import CEOAgent
        from multiclaws.config import get_config
        from multiclaws.llm.provider import LLMResponse

        cfg = get_config()
        agent = CEOAgent(config=cfg)
        agent._store = store

        # First response: tool call; second: final answer
        tool_call_json = json.dumps({"tool": "file_list", "args": {"path": "."}})
        mock_router = MagicMock()
        mock_router.complete_full = AsyncMock(side_effect=[
            LLMResponse(content=tool_call_json, input_tokens=10, output_tokens=5,
                        cost_usd=0.0, latency_ms=50),
            LLMResponse(content="Files listed.", input_tokens=15, output_tokens=6,
                        cost_usd=0.0, latency_ms=50),
        ])
        agent._router = mock_router

        mock_registry = MagicMock()
        mock_registry.schemas_for = MagicMock(return_value=[])
        mock_registry.execute = AsyncMock(return_value={"files": ["a.txt"]})
        agent._registry = mock_registry

        result = await agent.handle_task({
            "message": "List files please",
            "session_id": "test:s",
        })
        assert result["result"] == "Files listed."
        mock_registry.execute.assert_called_once()


# ── Researcher handle_task ────────────────────────────────────────────────────

class TestResearcherHandleTask:
    @pytest.fixture
    def store(self, tmp_path):
        from multiclaws.memory.store import MemoryStore
        return MemoryStore(db_path=tmp_path / "test.db")

    @pytest.mark.asyncio
    async def test_researcher_returns_result(self, store):
        from multiclaws.roles.researcher import ResearcherAgent
        from multiclaws.config import get_config
        from multiclaws.llm.provider import LLMResponse

        cfg = get_config()
        agent = ResearcherAgent(config=cfg)
        agent._store = store

        mock_router = MagicMock()
        mock_router.complete_full = AsyncMock(return_value=LLMResponse(
            content="Python is a programming language.",
            input_tokens=10, output_tokens=8, cost_usd=0.0, latency_ms=50,
        ))
        agent._router = mock_router

        result = await agent.handle_task({"query": "What is Python?"})
        assert "result" in result
        assert result["result"] == "Python is a programming language."


# ── Coder handle_task ─────────────────────────────────────────────────────────

class TestCoderHandleTask:
    @pytest.fixture
    def store(self, tmp_path):
        from multiclaws.memory.store import MemoryStore
        return MemoryStore(db_path=tmp_path / "test.db")

    @pytest.mark.asyncio
    async def test_coder_returns_result(self, store):
        from multiclaws.roles.coder import CoderAgent
        from multiclaws.config import get_config
        from multiclaws.llm.provider import LLMResponse

        cfg = get_config()
        agent = CoderAgent(config=cfg)
        agent._store = store

        mock_router = MagicMock()
        mock_router.complete_full = AsyncMock(return_value=LLMResponse(
            content="print('hello')",
            input_tokens=10, output_tokens=5, cost_usd=0.0, latency_ms=50,
        ))
        agent._router = mock_router

        result = await agent.handle_task({"instruction": "Write hello world"})
        assert "result" in result
