-- universe.db schema v5 (Phase 4 fixes).

-- Items deleted for good (not just trashed) disappear from `items`, so the universe's incremental refresh
-- (`since`) learns about them here. Kept 30 days.
CREATE TABLE removed_items (
    id         TEXT PRIMARY KEY,
    removed_at TEXT NOT NULL
);
CREATE INDEX removed_items_at ON removed_items (removed_at);

-- Notes written before Phase 4 never had their [[wikilinks]] read. If this vault has notes, leave a flag;
-- Core's housekeeping then queues a one-time background job to read them (vault_runtime.py).
INSERT INTO settings (key, value, updated_at)
SELECT 'vault.wikilinks_backfill', 'pending', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE EXISTS (
    SELECT 1 FROM items
    WHERE trashed_at IS NULL AND (lower(path) LIKE '%.md' OR lower(path) LIKE '%.markdown')
);
