-- universe.db schema v2 (Phase 2): vault items, versions, pipeline stages, chunks + full-text indexes,
-- tags, project membership, provenance, watched folders, the job queue, local API keys and backups.

CREATE TABLE sources (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('drop', 'watched_folder', 'quick_capture', 'clipboard', 'api',
                                             'importer', 'agent', 'web', 'screen', 'vault')),
    origin     TEXT,
    importer   TEXT,
    api_key_id TEXT,
    agent_id   TEXT,
    extra      TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE items (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL CHECK (type IN ('note', 'idea', 'song', 'audio', 'voice_memo', 'photo', 'video',
                                                  'document', 'pdf', 'spreadsheet', 'code_repo', 'code_file', 'link',
                                                  'screenshot', 'transcript', 'folder', 'file')),
    title           TEXT NOT NULL,
    slug            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'inbox' CHECK (status IN ('inbox', 'triaged', 'active', 'archived')),
    idea_stage      TEXT CHECK (idea_stage IN ('nebula', 'protostar', 'star', 'promoted')),
    path            TEXT NOT NULL,                 -- relative to the vault root, '/' separators
    mime            TEXT,
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    content_hash    TEXT NOT NULL,                 -- sha256 of the current version
    current_version INTEGER NOT NULL DEFAULT 1,
    captured_at     TEXT NOT NULL,                 -- when it happened (EXIF, tags, file time)
    summary         TEXT NOT NULL DEFAULT '',
    metadata        TEXT NOT NULL DEFAULT '{}',
    lat             REAL,
    lon             REAL,
    pinned          INTEGER NOT NULL DEFAULT 0,
    open_count      INTEGER NOT NULL DEFAULT 0,
    last_opened_at  TEXT,
    source_id       TEXT REFERENCES sources (id) ON DELETE SET NULL,
    pipeline_status TEXT NOT NULL DEFAULT 'pending' CHECK (pipeline_status IN ('pending', 'processing', 'done', 'failed')),
    trashed_at      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX items_path ON items (path);
CREATE INDEX items_content_hash ON items (content_hash);
CREATE INDEX items_type_captured ON items (type, captured_at DESC);
CREATE INDEX items_captured ON items (captured_at DESC);
CREATE INDEX items_created ON items (created_at DESC);
CREATE INDEX items_status ON items (status);
CREATE INDEX items_last_opened ON items (last_opened_at DESC);
CREATE INDEX items_trashed ON items (trashed_at);

CREATE TABLE versions (
    id           TEXT PRIMARY KEY,
    item_id      TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    n            INTEGER NOT NULL,
    path         TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    created_by   TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    UNIQUE (item_id, n)
);

CREATE TABLE item_stages (
    item_id       TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    stage         TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed', 'skipped')),
    model         TEXT,
    model_version TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    detail        TEXT,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (item_id, stage)
);

-- Retrieval units. The integer id is the FTS5 rowid and the LanceDB chunk_id.
CREATE TABLE chunks (
    id          INTEGER PRIMARY KEY,
    item_id     TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    version_n   INTEGER NOT NULL DEFAULT 1,
    ord         INTEGER NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'text' CHECK (kind IN ('text', 'ocr', 'caption', 'metadata')),
    text        TEXT NOT NULL,
    page        INTEGER,
    start_ms    INTEGER,
    end_ms      INTEGER,
    char_start  INTEGER,
    char_end    INTEGER,
    token_count INTEGER
);
CREATE INDEX chunks_item ON chunks (item_id, ord);

CREATE VIRTUAL TABLE chunks_fts USING fts5 (
    text, content = 'chunks', content_rowid = 'id', tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER chunks_au AFTER UPDATE OF text ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunks_fts (rowid, text) VALUES (new.id, new.text);
END;

-- Title and metadata search for the fast path (maintained by the vault store), plus a trigram index
-- on titles so a fragment like "4471" finds "parcel-4471-seller-call".
CREATE VIRTUAL TABLE items_fts USING fts5 (
    item_id UNINDEXED, title, tags, meta, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE items_trigram USING fts5 (item_id UNINDEXED, title, tokenize = 'trigram');

CREATE TABLE tags (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color_token TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE item_tags (
    item_id    TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    tag_id     TEXT NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    state      TEXT NOT NULL DEFAULT 'confirmed' CHECK (state IN ('suggested', 'confirmed')),
    source     TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (item_id, tag_id)
);
CREATE INDEX item_tags_tag ON item_tags (tag_id);

CREATE TABLE item_projects (
    item_id    TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    added_by   TEXT NOT NULL,
    added_at   TEXT NOT NULL,
    PRIMARY KEY (item_id, project_id)
);
CREATE INDEX item_projects_project ON item_projects (project_id);

CREATE TABLE watched_folders (
    id                 TEXT PRIMARY KEY,
    path               TEXT NOT NULL UNIQUE,
    recursive          INTEGER NOT NULL DEFAULT 1,
    include_globs      TEXT NOT NULL DEFAULT '[]',
    exclude_globs      TEXT NOT NULL DEFAULT '[]',
    default_project_id TEXT REFERENCES projects (id) ON DELETE SET NULL,
    enabled            INTEGER NOT NULL DEFAULT 1,
    last_scan_at       TEXT,
    last_error         TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

-- Files seen outside the vault (watched folders), so unchanged files aren't re-hashed on every scan
-- and an edited source becomes a new version of the item it produced.
CREATE TABLE source_files (
    path         TEXT PRIMARY KEY,
    folder_id    TEXT REFERENCES watched_folders (id) ON DELETE CASCADE,
    item_id      TEXT REFERENCES items (id) ON DELETE SET NULL,
    size_bytes   INTEGER NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    seen_at      TEXT NOT NULL
);
CREATE INDEX source_files_item ON source_files (item_id);

-- The job queue (ADR-0002). A finished job's idempotency_key is cleared so the same work can be queued again.
CREATE TABLE jobs (
    id               TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,
    item_id          TEXT REFERENCES items (id) ON DELETE CASCADE,
    priority_class   TEXT NOT NULL CHECK (priority_class IN ('realtime', 'interactive', 'background')),
    priority         INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL CHECK (status IN ('queued', 'leased', 'succeeded', 'dead', 'cancelled')),
    attempts         INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 5,
    run_after        TEXT NOT NULL,
    lease_owner      TEXT,
    lease_expires_at TEXT,
    progress         REAL NOT NULL DEFAULT 0,
    payload          TEXT NOT NULL DEFAULT '{}',
    result           TEXT,
    error            TEXT,
    idempotency_key  TEXT UNIQUE,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    finished_at      TEXT
);
CREATE INDEX jobs_claim ON jobs (status, run_after);
CREATE INDEX jobs_item ON jobs (item_id);
CREATE INDEX jobs_finished ON jobs (finished_at);

CREATE TABLE api_keys (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    scopes       TEXT NOT NULL,                    -- JSON array: capture, search
    key_hash     TEXT NOT NULL UNIQUE,             -- sha256 of the key; the key itself is shown once
    prefix       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);

CREATE TABLE backups (
    id                 TEXT PRIMARY KEY,
    kind               TEXT NOT NULL CHECK (kind IN ('scheduled', 'pre_upgrade', 'pre_migration', 'manual')),
    target             TEXT NOT NULL,
    restic_snapshot_id TEXT,
    status             TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    files_new          INTEGER,
    bytes_added        INTEGER,
    error              TEXT,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    verified_at        TEXT
);
CREATE INDEX backups_started ON backups (started_at DESC);
