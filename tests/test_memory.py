"""Tests for the memory store."""

import pytest

from teamclaws.memory.store import MemoryStore
from teamclaws.memory.summarizer import extract_keywords, estimate_token_count


@pytest.fixture
def memory(tmp_path):
    """Create a temporary memory store."""
    db_path = tmp_path / "test.db"
    store = MemoryStore(db_path)
    store.connect()
    yield store
    store.close()


class TestMessageOperations:
    """Tests for message CRUD operations."""

    def test_save_and_retrieve(self, memory):
        memory.save_message("conv1", "ceo", "user", "Hello")
        memory.save_message("conv1", "ceo", "assistant", "Hi there!")
        messages = memory.get_recent_messages("conv1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_message_limit(self, memory):
        for i in range(20):
            memory.save_message("conv1", "ceo", "user", f"Message {i}")
        messages = memory.get_recent_messages("conv1", limit=5)
        assert len(messages) == 5

    def test_turn_count(self, memory):
        memory.save_message("conv1", "ceo", "user", "Q1")
        memory.save_message("conv1", "ceo", "assistant", "A1")
        memory.save_message("conv1", "ceo", "user", "Q2")
        assert memory.get_turn_count("conv1") == 2

    def test_clear_conversation(self, memory):
        memory.save_message("conv1", "ceo", "user", "Hello")
        memory.save_message("conv1", "ceo", "assistant", "Hi")
        count = memory.clear_conversation("conv1")
        assert count == 2
        assert memory.get_recent_messages("conv1") == []

    def test_separate_conversations(self, memory):
        memory.save_message("conv1", "ceo", "user", "Conv 1 message")
        memory.save_message("conv2", "ceo", "user", "Conv 2 message")
        assert len(memory.get_recent_messages("conv1")) == 1
        assert len(memory.get_recent_messages("conv2")) == 1


class TestSummaryOperations:
    """Tests for summary storage and search."""

    def test_save_and_search(self, memory):
        memory.save_summary(
            "conv1", "ceo", "User asked about Python programming", 1, 5, "python,programming"
        )
        results = memory.search_summaries("python")
        assert len(results) == 1
        assert "Python" in results[0]["summary"]

    def test_search_by_keyword(self, memory):
        memory.save_summary("conv1", "ceo", "Discussion about databases", 1, 5, "database,sql")
        memory.save_summary("conv1", "ceo", "Discussion about frontend", 6, 10, "react,css")
        results = memory.search_summaries("database")
        assert len(results) == 1

    def test_search_empty(self, memory):
        results = memory.search_summaries("nonexistent")
        assert results == []


class TestAgentOperations:
    """Tests for agent registry in DB."""

    def test_register_agent(self, memory):
        memory.register_agent("ceo", "Main agent", ["list_files", "read_file"])
        agent = memory.get_agent("ceo")
        assert agent is not None
        assert agent["role_name"] == "ceo"
        assert "list_files" in agent["permissions"]

    def test_deactivate_agent(self, memory):
        memory.register_agent("test", "Test agent", [])
        assert memory.deactivate_agent("test")
        assert memory.get_agent("test") is None

    def test_list_agents(self, memory):
        memory.register_agent("ceo", "CEO", ["list_files"])
        memory.register_agent("exec", "Executor", ["run_python"])
        agents = memory.list_agents()
        assert len(agents) == 2


class TestTokenTracking:
    """Tests for token usage tracking."""

    def test_track_usage(self, memory):
        memory.track_token_usage("ceo", "gpt-4o-mini", 100, 50, 0.001)
        stats = memory.get_token_stats()
        assert stats["total_tokens"] == 150
        assert stats["total_cost"] == 0.001

    def test_stats_by_agent(self, memory):
        memory.track_token_usage("ceo", "gpt-4o-mini", 100, 50, 0.001)
        memory.track_token_usage("exec", "gpt-4o-mini", 200, 100, 0.002)
        ceo_stats = memory.get_token_stats("ceo")
        assert ceo_stats["total_tokens"] == 150


class TestMemoryStats:
    """Tests for overall memory stats."""

    def test_stats(self, memory):
        memory.save_message("conv1", "ceo", "user", "Hello")
        memory.register_agent("ceo", "CEO", [])
        stats = memory.get_memory_stats()
        assert stats["total_messages"] == 1
        assert stats["active_agents"] == 1
        assert stats["db_size_bytes"] > 0


class TestExtractKeywords:
    """Tests for keyword extraction."""

    def test_basic_extraction(self):
        text = "The user asked about Python programming and database optimization"
        keywords = extract_keywords(text)
        assert "python" in keywords
        assert "programming" in keywords

    def test_stop_word_filtering(self):
        text = "The and but or not with from this that"
        keywords = extract_keywords(text)
        assert len(keywords) == 0

    def test_max_keywords(self):
        text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
        keywords = extract_keywords(text, max_keywords=5)
        assert len(keywords) <= 5


class TestEstimateTokenCount:
    """Tests for token count estimation."""

    def test_basic_estimate(self):
        text = "Hello world, this is a test message."
        count = estimate_token_count(text)
        assert count > 0
        assert count < 100

    def test_empty_string(self):
        assert estimate_token_count("") == 1
