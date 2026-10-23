-- universe.db schema v6: neural pathways (SPEC §10, owner-approved 2026-10-14). Every time two items fire
-- together (you open one right after the other, or an agent moves from one to the next in a task) a row is
-- recorded here, so the brain layer (Phase 9) can strengthen the links you use and fade the ones you don't.
CREATE TABLE link_activity (
    id     TEXT PRIMARY KEY,
    a_id   TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,  -- the pair, ordered a_id < b_id
    b_id   TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('sequence', 'agent')),
    actor  TEXT NOT NULL,
    at     TEXT NOT NULL,
    CHECK (a_id < b_id)
);
CREATE INDEX link_activity_pair ON link_activity (a_id, b_id);
CREATE INDEX link_activity_at ON link_activity (at);
