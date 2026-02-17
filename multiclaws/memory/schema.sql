-- TeamClaws v3.2 SQLite WAL-mode schema
-- All tables from §5 (Memory) + §6 (Tasks)

PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────
-- CONVERSATION TURNS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    agent_role  TEXT,
    role        TEXT    CHECK(role IN ('user','assistant','system','tool')),
    content     TEXT,
    tokens      INTEGER DEFAULT 0,
    summarized  INTEGER DEFAULT 0,  -- 0=no, 1=yes
    ts          TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);

-- ─────────────────────────────────────────
-- SUMMARIES
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    content     TEXT,
    turn_range  TEXT,               -- e.g. "45-60"
    ts          TEXT    DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────
-- AGENT STATE (heartbeat / crash recovery)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_state (
    agent_role  TEXT    PRIMARY KEY,
    last_task_id TEXT,
    status      TEXT    CHECK(status IN ('idle','working','crashed','killed')) DEFAULT 'idle',
    pid         INTEGER,
    updated_at  TEXT    DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────
-- TASK QUEUE  §6-2
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT    PRIMARY KEY,
    parent_id   TEXT,               -- for sub-tasks
    assigned_to TEXT,
    status      TEXT    DEFAULT 'pending'
                        CHECK(status IN ('pending','assigned','running','done','failed')),
    input_data  TEXT,               -- JSON
    output_data TEXT,               -- JSON
    created_at  TEXT    DEFAULT (datetime('now')),
    updated_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, assigned_to);

-- ─────────────────────────────────────────
-- LLM COST LOG  §4-3
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cost_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    DEFAULT (datetime('now')),
    agent_role      TEXT,
    provider        TEXT,
    model           TEXT,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cost_usd        REAL    DEFAULT 0.0,
    latency_ms      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cost_ts ON cost_log(ts);

-- ─────────────────────────────────────────
-- SECURITY AUDIT LOG  §7-3
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    DEFAULT (datetime('now')),
    agent_role  TEXT,
    tool_name   TEXT,
    arguments   TEXT,               -- JSON (sanitized)
    result      TEXT    CHECK(result IN ('allowed','denied','error')),
    detail      TEXT
);
