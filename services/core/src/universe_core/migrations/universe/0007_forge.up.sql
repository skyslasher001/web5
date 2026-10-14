-- universe.db schema v7 (Phase 5, ADR-0014): Forge's issues and proposals.

-- What needs fixing: grouped errors, failed jobs, failing checks and your bug reports, ranked.
CREATE TABLE forge_issues (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL CHECK (source IN ('error', 'job', 'check', 'report')),
    fingerprint TEXT NOT NULL UNIQUE,                 -- duplicates collapse onto one issue
    title       TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',             -- untrusted: logs, stack traces, your words
    severity    TEXT NOT NULL DEFAULT 'error' CHECK (severity IN ('warning', 'error', 'critical')),
    count       INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'working', 'proposed', 'fixed', 'ignored')),
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    proposal_id TEXT
);
CREATE INDEX forge_issues_status ON forge_issues (status, last_seen DESC);

-- A tested fix waiting for you, and everything about it, kept forever.
CREATE TABLE forge_proposals (
    id                TEXT PRIMARY KEY,
    issue_id          TEXT REFERENCES forge_issues (id) ON DELETE SET NULL,
    task_id           TEXT,
    title             TEXT NOT NULL,
    root_cause        TEXT NOT NULL DEFAULT '',
    branch            TEXT NOT NULL,
    base_commit       TEXT NOT NULL,
    head_commit       TEXT,
    diff              TEXT NOT NULL DEFAULT '',
    diff_sha          TEXT,
    files             TEXT NOT NULL DEFAULT '[]',     -- JSON [{path, status}]
    repro_test        TEXT,                           -- the test that must fail on base and pass on head
    verification      TEXT NOT NULL DEFAULT '{}',     -- JSON report
    reviews           TEXT NOT NULL DEFAULT '{}',     -- JSON {critic, sentinel}
    risk              TEXT CHECK (risk IN ('low', 'medium', 'high')),
    rollback_plan     TEXT NOT NULL DEFAULT '',
    touches_protected INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                      ('draft', 'verifying', 'failed', 'ready', 'approved', 'applied', 'rolled_back', 'rejected')),
    release           TEXT,                           -- the release tag it was applied as
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    decided_at        TEXT
);
CREATE INDEX forge_proposals_status ON forge_proposals (status, created_at DESC);
