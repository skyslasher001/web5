-- universe.db schema v1 (Phase 1): projects, conversations, messages, errors, settings.
-- Later phases add items, links, jobs, memories, ... as new numbered migrations.

CREATE TABLE projects (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    slug           TEXT NOT NULL UNIQUE,
    description    TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'done', 'archived')),
    color_token    TEXT NOT NULL DEFAULT 'cyan',
    layout_seed    INTEGER NOT NULL DEFAULT 0,
    goals          TEXT NOT NULL DEFAULT '[]',
    origin_idea_id TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE conversations (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    project_id    TEXT REFERENCES projects (id) ON DELETE SET NULL,
    channel       TEXT NOT NULL DEFAULT 'chat' CHECK (channel IN ('chat', 'voice', 'command_bar')),
    vault_item_id TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX conversations_updated ON conversations (updated_at DESC);

CREATE TABLE messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    agent_id        TEXT,
    content         TEXT NOT NULL,
    citations       TEXT NOT NULL DEFAULT '[]',
    task_id         TEXT,
    modality        TEXT NOT NULL DEFAULT 'text',
    model           TEXT,
    status          TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('complete', 'cancelled', 'failed')),
    first_token_ms  INTEGER,
    total_ms        INTEGER,
    created_at      TEXT NOT NULL
);
CREATE INDEX messages_conversation ON messages (conversation_id, created_at);

CREATE TABLE errors (
    id             TEXT PRIMARY KEY,
    fingerprint    TEXT NOT NULL UNIQUE,
    service        TEXT NOT NULL,
    kind           TEXT NOT NULL,
    message        TEXT NOT NULL,
    stack          TEXT NOT NULL DEFAULT '',
    context        TEXT NOT NULL DEFAULT '{}',
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    count          INTEGER NOT NULL DEFAULT 1,
    severity       TEXT NOT NULL DEFAULT 'error' CHECK (severity IN ('warning', 'error', 'critical')),
    status         TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'triaged', 'in_progress', 'fixed', 'ignored')),
    forge_issue_id TEXT
);
CREATE INDEX errors_last_seen ON errors (last_seen DESC);

CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    protected  INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
