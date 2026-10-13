-- universe.db v3 (Phase 3): the agent engine. Tasks and their traces, approvals, permission rules,
-- memories, the usage ledger and MCP server definitions (ARCHITECTURE.md §4.1, ADR-0011).

CREATE TABLE agent_tasks (
    id              TEXT PRIMARY KEY,
    parent_id       TEXT REFERENCES agent_tasks (id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations (id) ON DELETE SET NULL,
    agent_id        TEXT NOT NULL,
    title           TEXT NOT NULL,
    input           TEXT NOT NULL,
    output          TEXT,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'waiting_approval', 'done', 'failed', 'cancelled')),
    steps_used      INTEGER NOT NULL DEFAULT 0,
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0,
    model           TEXT,
    tainted         INTEGER NOT NULL DEFAULT 0,
    correlation_id  TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);
CREATE INDEX agent_tasks_status ON agent_tasks (status, created_at DESC);
CREATE INDEX agent_tasks_parent ON agent_tasks (parent_id);

CREATE TABLE task_steps (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES agent_tasks (id) ON DELETE CASCADE,
    n           INTEGER NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('llm_call', 'tool_call', 'tool_result', 'delegate', 'message', 'review')),
    model       TEXT,
    tool        TEXT,
    args        TEXT NOT NULL DEFAULT '{}',
    result      TEXT,
    decision    TEXT,
    tokens      INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    UNIQUE (task_id, n)
);

CREATE TABLE approvals (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('tool_call', 'memory_update', 'budget_raise')),
    requester   TEXT NOT NULL,
    task_id     TEXT REFERENCES agent_tasks (id) ON DELETE CASCADE,
    tool        TEXT,
    args        TEXT NOT NULL DEFAULT '{}',
    risk        TEXT NOT NULL CHECK (risk IN ('low', 'medium', 'high')),
    summary     TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'denied', 'expired', 'auto_approved')),
    rule_id     TEXT,
    decided_via TEXT CHECK (decided_via IN ('ui', 'voice', 'native_dialog', 'rule')),
    created_at  TEXT NOT NULL,
    decided_at  TEXT,
    expires_at  TEXT NOT NULL
);
CREATE INDEX approvals_status ON approvals (status, created_at DESC);

-- Written only by the protected permission store, from your UI session (never by an agent).
CREATE TABLE permission_rules (
    id                   TEXT PRIMARY KEY,
    agent_id             TEXT NOT NULL DEFAULT '*',
    tool                 TEXT NOT NULL,
    decision             TEXT NOT NULL CHECK (decision IN ('allow', 'ask', 'deny')),
    scope                TEXT NOT NULL DEFAULT '{}',
    applies_when_tainted INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    expires_at           TEXT
);

CREATE TABLE memories (
    id                TEXT PRIMARY KEY,
    type              TEXT NOT NULL CHECK (type IN ('episodic', 'semantic', 'procedural')),
    scope             TEXT NOT NULL,
    content           TEXT NOT NULL,
    data              TEXT NOT NULL DEFAULT '{}',
    importance        REAL NOT NULL DEFAULT 0.5,
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'proposed', 'superseded')),
    supersedes_id     TEXT REFERENCES memories (id) ON DELETE SET NULL,
    source_item_id    TEXT,
    source_message_id TEXT,
    source_task_id    TEXT,
    created_by        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    last_used_at      TEXT
);
CREATE INDEX memories_scope ON memories (scope, status);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, content='memories', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts (rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
END;
CREATE TRIGGER memories_au AFTER UPDATE OF content ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
    INSERT INTO memories_fts (rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE usage_ledger (
    id         TEXT PRIMARY KEY,
    ts         TEXT NOT NULL,
    task_id    TEXT,
    agent_id   TEXT,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_usd   REAL NOT NULL DEFAULT 0
);
CREATE INDEX usage_ledger_ts ON usage_ledger (ts);

CREATE TABLE mcp_servers (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    command    TEXT NOT NULL,
    args       TEXT NOT NULL DEFAULT '[]',
    env        TEXT NOT NULL DEFAULT '{}',
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
