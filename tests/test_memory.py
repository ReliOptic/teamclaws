"""Tests for multiclaws.memory.store — MemoryStore CRUD operations."""
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def store(tmp_path):
    from multiclaws.memory.store import MemoryStore
    return MemoryStore(db_path=tmp_path / "test.db", short_term_maxlen=5)


# ── push_turn / get_context ───────────────────────────────────────────────────

class TestShortTermMemory:
    def test_push_and_get(self, store):
        store.push_turn("s1", "user", "Hello", agent_role="ceo")
        store.push_turn("s1", "assistant", "Hi!", agent_role="ceo")
        ctx = store.get_context("s1")
        assert len(ctx) == 2
        assert ctx[0]["role"] == "user"
        assert ctx[1]["role"] == "assistant"

    def test_separate_sessions(self, store):
        store.push_turn("s1", "user", "Session 1")
        store.push_turn("s2", "user", "Session 2")
        assert len(store.get_context("s1")) == 1
        assert len(store.get_context("s2")) == 1

    def test_maxlen_enforced(self, store):
        for i in range(10):
            store.push_turn("s1", "user", f"msg {i}")
        ctx = store.get_context("s1")
        assert len(ctx) <= store.short_term_maxlen

    def test_returns_id(self, store):
        turn_id = store.push_turn("s1", "user", "msg")
        assert isinstance(turn_id, int)
        assert turn_id > 0


# ── Summarization ────────────────────────────────────────────────────────────

class TestSummarization:
    def test_count_unsummarized(self, store):
        store.push_turn("s1", "user", "A")
        store.push_turn("s1", "assistant", "B")
        count = store.count_unsummarized_turns("s1")
        assert count == 2

    def test_save_and_load_summary(self, store):
        store.push_turn("s1", "user", "msg1")
        store.push_turn("s1", "assistant", "msg2")
        store.save_summary("s1", "ceo", "Summary of conversation", turn_range="1-2")
        summaries = store.load_latest_summaries("s1")
        assert len(summaries) == 1
        assert "Summary" in summaries[0]

    def test_mark_summarized(self, store):
        tid = store.push_turn("s1", "user", "to summarize")
        store.mark_summarized([tid])
        count = store.count_unsummarized_turns("s1")
        assert count == 0

    def test_get_unsummarized_turns(self, store):
        store.push_turn("s1", "user", "A")
        store.push_turn("s1", "assistant", "B")
        turns = store.get_unsummarized_turns("s1")
        assert len(turns) == 2


# ── Agent State ───────────────────────────────────────────────────────────────

class TestAgentState:
    def test_upsert_and_read(self, store):
        store.upsert_agent_state("ceo", "working", pid=1234)
        with store._conn() as conn:
            row = conn.execute(
                "SELECT status, pid FROM agent_state WHERE agent_role=?", ("ceo",)
            ).fetchone()
        assert row["status"] == "working"
        assert row["pid"] == 1234

    def test_upsert_updates_existing(self, store):
        store.upsert_agent_state("ceo", "idle")
        store.upsert_agent_state("ceo", "crashed")
        with store._conn() as conn:
            row = conn.execute(
                "SELECT status FROM agent_state WHERE agent_role=?", ("ceo",)
            ).fetchone()
        assert row["status"] == "crashed"


# ── Task Queue ────────────────────────────────────────────────────────────────

class TestTaskQueue:
    def test_create_and_claim(self, store):
        task_id = store.create_task("coder", {"message": "write hello.py"})
        assert task_id is not None
        claimed = store.claim_task("coder")
        assert claimed is not None
        assert claimed["id"] == task_id
        assert claimed["status"] == "running"

    def test_claim_returns_none_when_empty(self, store):
        result = store.claim_task("coder")
        assert result is None

    def test_complete_task_done(self, store):
        task_id = store.create_task("coder", {"msg": "x"})
        store.claim_task("coder")
        store.complete_task(task_id, {"result": "done"}, success=True)
        task = store.get_task(task_id)
        assert task["status"] == "done"

    def test_complete_task_failed(self, store):
        task_id = store.create_task("coder", {"msg": "x"})
        store.claim_task("coder")
        store.complete_task(task_id, {"error": "oops"}, success=False)
        task = store.get_task(task_id)
        assert task["status"] == "failed"

    def test_get_nonexistent_task(self, store):
        result = store.get_task("nonexistent-id")
        assert result is None


# ── Cost Tracking ─────────────────────────────────────────────────────────────

class TestCostTracking:
    def test_log_and_get_daily(self, store):
        store.log_cost("ceo", "groq", "llama-3.1-8b-instant",
                       input_tokens=100, output_tokens=50, cost_usd=0.0005, latency_ms=300)
        daily = store.get_daily_cost()
        assert daily == pytest.approx(0.0005)

    def test_log_multiple_and_sum(self, store):
        store.log_cost("ceo", "groq", "llama",
                       input_tokens=100, output_tokens=50, cost_usd=0.001, latency_ms=200)
        store.log_cost("researcher", "groq", "llama",
                       input_tokens=200, output_tokens=100, cost_usd=0.002, latency_ms=400)
        daily = store.get_daily_cost()
        assert daily == pytest.approx(0.003)

    def test_get_weekly_cost(self, store):
        store.log_cost("ceo", "groq", "llama",
                       input_tokens=10, output_tokens=5, cost_usd=0.0001, latency_ms=100)
        weekly = store.get_weekly_cost()
        assert weekly >= 0.0001


# ── Audit Log ────────────────────────────────────────────────────────────────

class TestAuditLog:
    def test_audit_writes_to_db(self, store):
        store.audit("ceo", "file_write", {"path": "x.txt"}, "allowed", "")
        with store._conn() as conn:
            row = conn.execute(
                "SELECT * FROM audit_log WHERE tool_name=?", ("file_write",)
            ).fetchone()
        assert row is not None
        assert row["agent_role"] == "ceo"
        assert row["result"] == "allowed"


# ── Session Binding ───────────────────────────────────────────────────────────

class TestSessionBinding:
    def test_make_session_id_stable(self, store):
        sid1 = store.make_session_id("cli", "user1")
        sid2 = store.make_session_id("cli", "user1")
        assert sid1 == sid2

    def test_make_session_id_different_users(self, store):
        sid1 = store.make_session_id("cli", "user1")
        sid2 = store.make_session_id("cli", "user2")
        assert sid1 != sid2

    def test_make_session_id_different_platforms(self, store):
        sid1 = store.make_session_id("cli", "user1")
        sid2 = store.make_session_id("telegram", "user1")
        assert sid1 != sid2
