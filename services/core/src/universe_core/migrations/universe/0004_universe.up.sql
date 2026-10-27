-- universe.db schema v4 (Phase 4): links between items (filaments, backlinks, the graph layout) and cached
-- layouts (ADR-0012).

CREATE TABLE links (
    id         TEXT PRIMARY KEY,
    from_id    TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    to_id      TEXT REFERENCES items (id) ON DELETE CASCADE,
    to_title   TEXT,                              -- a [[wikilink]] whose target doesn't exist yet
    kind       TEXT NOT NULL CHECK (kind IN ('wikilink', 'manual', 'agent')),
    state      TEXT NOT NULL DEFAULT 'confirmed' CHECK (state IN ('confirmed', 'suggested')),
    strength   REAL NOT NULL DEFAULT 1.0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (to_id IS NOT NULL OR to_title IS NOT NULL),
    CHECK (to_id IS NULL OR to_id != from_id)
);
CREATE UNIQUE INDEX links_pair ON links (from_id, to_id, kind) WHERE to_id IS NOT NULL;
CREATE UNIQUE INDEX links_pending_pair ON links (from_id, to_title COLLATE NOCASE) WHERE to_id IS NULL;
CREATE INDEX links_to ON links (to_id);
CREATE INDEX links_pending ON links (to_title COLLATE NOCASE) WHERE to_id IS NULL;

CREATE INDEX items_title_nocase ON items (title COLLATE NOCASE);
CREATE INDEX items_updated ON items (updated_at);

CREATE TABLE layout_cache (
    kind       TEXT NOT NULL,                     -- 'semantic'
    model      TEXT NOT NULL,                     -- the vector table the layout was computed from
    item_count INTEGER NOT NULL,
    data       TEXT NOT NULL,                     -- JSON {ids: [...], positions: [x, y, z, ...]}
    created_at TEXT NOT NULL,
    PRIMARY KEY (kind, model)
);
