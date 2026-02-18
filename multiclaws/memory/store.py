"""
SQLite WAL-mode store: CRUD ops, session binding, cost tracking.
All queries are parameterized — no string interpolation.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

_SCHEMA = Path(__file__).parent / "schema.sql"


class MemoryStore:
    def __init__(self, db_path: str | Path, short_term_maxlen: int = 20) -> None:
        self.db_path = str(db_path)
        self.short_term_maxlen = short_term_maxlen
        self._short_term: dict[str, deque] = {}
        self._init_db()

    # ── DB init ──────────────────────────────────────────────────────────
    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA.read_text())

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Short-term memory ────────────────────────────────────────────────
    def get_short_term(self, session_id: str) -> deque:
        if session_id not in self._short_term:
            self._short_term[session_id] = deque(maxlen=self.short_term_maxlen)
        return self._short_term[session_id]

    def push_turn(self, session_id: str, role: str, content: str,
                  agent_role: str = "", tokens: int = 0) -> int:
        """Append turn to short-term deque AND persist to DB."""
        entry = {"role": role, "content": content}
        self.get_short_term(session_id).append(entry)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO turns (session_id, agent_role, role, content, tokens) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, agent_role, role, content, tokens),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_context(self, session_id: str) -> list[dict]:
        """Return short-term window for LLM context."""
        return list(self.get_short_term(session_id))

    # ── Long-term / summarization ────────────────────────────────────────
    def count_unsummarized_turns(self, session_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM turns WHERE session_id=? AND summarized=0",
                (session_id,),
            ).fetchone()
            return int(row["n"])

    def get_unsummarized_turns(self, session_id: str, limit: int = 15) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, role, content, tokens FROM turns "
                "WHERE session_id=? AND summarized=0 ORDER BY id LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_summarized(self, session_id: str, turn_ids: list[int]) -> None:
        if not turn_ids:
            return
        placeholders = ",".join("?" * len(turn_ids))
        with self._conn() as conn:
            conn.execute(
                f"UPDATE turns SET summarized=1 WHERE session_id=? AND id IN ({placeholders})",
                [session_id, *turn_ids],
            )

    def save_summary(self, session_id: str, content: str, turn_range: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO summaries (session_id, content, turn_range) VALUES (?, ?, ?)",
                (session_id, content, turn_range),
            )

    def load_latest_summaries(self, session_id: str, limit: int = 3) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT content FROM summaries WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [r["content"] for r in reversed(rows)]

    # ── Agent state ───────────────────────────────────────────────────────
    def upsert_agent_state(self, agent_role: str, status: str,
                           pid: int | None = None, last_task_id: str | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO agent_state (agent_role, status, pid, last_task_id, updated_at) "
                "VALUES (?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(agent_role) DO UPDATE SET "
                "status=excluded.status, pid=excluded.pid, "
                "last_task_id=COALESCE(excluded.last_task_id, last_task_id), "
                "updated_at=excluded.updated_at",
                (agent_role, status, pid, last_task_id),
            )

    def get_agent_state(self, agent_role: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM agent_state WHERE agent_role=?", (agent_role,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_agent_states(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM agent_state").fetchall()
            return [dict(r) for r in rows]

    # ── Task queue ────────────────────────────────────────────────────────
    def create_task(self, assigned_to: str, input_data: dict,
                    parent_id: str | None = None) -> str:
        task_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO tasks (id, parent_id, assigned_to, input_data) VALUES (?, ?, ?, ?)",
                (task_id, parent_id, assigned_to, json.dumps(input_data)),
            )
        return task_id

    def claim_task(self, agent_role: str) -> dict | None:
        """Atomically claim next pending task for agent."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE status='pending' AND assigned_to=? "
                "ORDER BY created_at LIMIT 1",
                (agent_role,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE tasks SET status='running', updated_at=datetime('now') WHERE id=?",
                (row["id"],),
            )
            task = dict(row)
        task["input_data"] = json.loads(task["input_data"] or "{}")
        return task

    def complete_task(self, task_id: str, output_data: dict,
                      success: bool = True) -> None:
        status = "done" if success else "failed"
        with self._conn() as conn:
            conn.execute(
                "UPDATE tasks SET status=?, output_data=?, updated_at=datetime('now') WHERE id=?",
                (status, json.dumps(output_data), task_id),
            )

    def get_task(self, task_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            t = dict(row)
        t["input_data"] = json.loads(t["input_data"] or "{}")
        t["output_data"] = json.loads(t["output_data"] or "{}")
        return t

    # ── Cost tracking ──────────────────────────────────────────────────────
    def log_cost(self, agent_role: str, provider: str, model: str,
                 input_tokens: int, output_tokens: int,
                 cost_usd: float, latency_ms: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO cost_log "
                "(agent_role, provider, model, input_tokens, output_tokens, cost_usd, latency_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (agent_role, provider, model, input_tokens, output_tokens, cost_usd, latency_ms),
            )

    def get_daily_cost(self) -> float:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd),0) as total FROM cost_log "
                "WHERE ts >= datetime('now','start of day')"
            ).fetchone()
            return float(row["total"])

    def get_weekly_cost(self) -> float:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd),0) as total FROM cost_log "
                "WHERE ts >= datetime('now','-7 days')"
            ).fetchone()
            return float(row["total"])

    # ── Audit log ──────────────────────────────────────────────────────────
    def audit(self, agent_role: str, tool_name: str,
               arguments: dict, result: str, detail: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO audit_log (agent_role, tool_name, arguments, result, detail) "
                "VALUES (?, ?, ?, ?, ?)",
                (agent_role, tool_name, json.dumps(arguments), result, detail),
            )

    # ── Task retry ─────────────────────────────────────────────────────────
    def fail_with_retry(self, task_id: str, error: str) -> bool:
        """Mark task as failed. If retries remain, reset to 'pending'. Returns True if retrying."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT retry_count, max_retries FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            if not row:
                return False
            retry_count = (row["retry_count"] or 0) + 1
            if retry_count <= (row["max_retries"] or 2):
                conn.execute(
                    "UPDATE tasks SET status='pending', retry_count=?, error_msg=?, "
                    "updated_at=datetime('now') WHERE id=?",
                    (retry_count, error, task_id),
                )
                return True
            conn.execute(
                "UPDATE tasks SET status='failed', retry_count=?, error_msg=?, "
                "updated_at=datetime('now') WHERE id=?",
                (retry_count, error, task_id),
            )
            return False

    # ── Task dependencies ──────────────────────────────────────────────────
    def add_task_dependency(self, task_id: str, depends_on: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO task_deps (task_id, depends_on) VALUES (?, ?)",
                (task_id, depends_on),
            )

    def claim_ready_task(self, agent_role: str) -> dict | None:
        """Claim next pending task whose dependencies are all 'done'."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE status='pending' AND assigned_to=? "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM task_deps td "
                "  JOIN tasks dep ON td.depends_on = dep.id "
                "  WHERE td.task_id = tasks.id AND dep.status != 'done'"
                ") ORDER BY created_at LIMIT 1",
                (agent_role,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE tasks SET status='running', updated_at=datetime('now') WHERE id=?",
                (row["id"],),
            )
            task = dict(row)
        task["input_data"] = json.loads(task["input_data"] or "{}")
        return task

    # ── Session binding ────────────────────────────────────────────────────
    @staticmethod
    def make_session_id(platform: str, user_id: str, context_hash: str = "") -> str:
        """Format: {platform}:{user_id}:{context_hash}"""
        return f"{platform}:{user_id}:{context_hash or 'default'}"

    def find_latest_session(self, user_id: str) -> str | None:
        """Cross-platform: find latest session for user regardless of platform."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT session_id, MAX(ts) FROM turns "
                "WHERE session_id LIKE ?",
                (f"%:{user_id}:%",),
            ).fetchone()
            return row["session_id"] if row and row["session_id"] else None

    def rebuild_short_term(self, session_id: str) -> None:
        """Reload last N turns from DB into short-term deque (after crash)."""
        st = self.get_short_term(session_id)
        st.clear()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM turns WHERE session_id=? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, self.short_term_maxlen),
            ).fetchall()
        for r in reversed(rows):
            st.append({"role": r["role"], "content": r["content"]})
