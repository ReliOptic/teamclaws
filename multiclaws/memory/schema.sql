-- TeamClaws v3.5 SQLite WAL-mode schema
-- 3계층 메모리 + FTS5 하이브리드 검색 지원

PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────
-- CONVERSATION TURNS  (L1 Active Thread)
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
-- FTS5 가상 테이블: turns 전문 검색  (v3.5)
-- ─────────────────────────────────────────
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    content,
    session_id UNINDEXED,
    tokenize = 'porter ascii'
);

-- 트리거: turns INSERT 시 자동 색인
CREATE TRIGGER IF NOT EXISTS turns_ai
AFTER INSERT ON turns
BEGIN
    INSERT INTO turns_fts(content, session_id)
    VALUES (new.content, new.session_id);
END;

-- ─────────────────────────────────────────
-- FTS5 가상 테이블: L3 MEMORY.md 청크 색인  (v3.5)
-- ─────────────────────────────────────────
CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts USING fts5(
    chunk_text,
    heading    UNINDEXED,
    chunk_id   UNINDEXED,
    tokenize = 'porter ascii'
);

-- ─────────────────────────────────────────
-- SUMMARIES  (Agentic Compaction 결과 캐시)
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
-- TASK QUEUE
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT    PRIMARY KEY,
    parent_id   TEXT,               -- for sub-tasks
    assigned_to TEXT,
    status      TEXT    DEFAULT 'pending'
                        CHECK(status IN ('pending','assigned','running','done','failed')),
    input_data  TEXT,               -- JSON
    output_data TEXT,               -- JSON
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 2,
    error_msg   TEXT,
    created_at  TEXT    DEFAULT (datetime('now')),
    updated_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, assigned_to);

-- ─────────────────────────────────────────
-- TASK DEPENDENCIES
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS task_deps (
    task_id     TEXT NOT NULL,
    depends_on  TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on)
);

-- ─────────────────────────────────────────
-- LLM COST LOG
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
-- SECURITY AUDIT LOG
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
