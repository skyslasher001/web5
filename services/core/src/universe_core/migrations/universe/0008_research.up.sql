-- universe.db schema v8 (Phase 6, ADR-0015): the research cache and watchlists.

-- Search results, cached with a TTL (fetched_at is epoch seconds; the cache sweeps stale rows on write).
CREATE TABLE research_search_cache (
    provider   TEXT NOT NULL,                       -- 'duckduckgo', 'searxng', …
    query      TEXT NOT NULL,
    results    TEXT NOT NULL,                        -- JSON [{title, url, snippet}]; untrusted (from the web)
    fetched_at REAL NOT NULL,
    PRIMARY KEY (provider, query)
);
CREATE INDEX research_search_cache_age ON research_search_cache (fetched_at);

-- Fetched pages (the extracted main text), cached with a TTL. This is also the snapshot a saved report cites.
CREATE TABLE research_page_cache (
    url        TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    text       TEXT NOT NULL DEFAULT '',            -- clean extracted text; untrusted (from the web)
    status     INTEGER NOT NULL DEFAULT 0,
    fetched_at REAL NOT NULL,
    truncated  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX research_page_cache_age ON research_page_cache (fetched_at);

-- Topics or pages the owner asked to watch. A scheduled Core job re-runs each and diffs the result.
CREATE TABLE watchlists (
    id               TEXT PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN ('topic', 'page')),
    target           TEXT NOT NULL,                 -- the search query (topic) or the URL (page)
    label            TEXT NOT NULL DEFAULT '',
    interval_s       INTEGER NOT NULL DEFAULT 86400,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    last_checked_at  TEXT,
    last_fingerprint TEXT,                           -- hash of the last result, to detect a change
    last_summary     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX watchlists_due ON watchlists (enabled, last_checked_at);

-- A detected change on a watchlist; surfaced in the Research panel (and, from Phase 9, the morning brief).
CREATE TABLE watchlist_hits (
    id           TEXT PRIMARY KEY,
    watchlist_id TEXT NOT NULL REFERENCES watchlists (id) ON DELETE CASCADE,
    found_at     TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    detail       TEXT NOT NULL DEFAULT '',          -- untrusted (web-derived)
    seen         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX watchlist_hits_recent ON watchlist_hits (watchlist_id, found_at DESC);
