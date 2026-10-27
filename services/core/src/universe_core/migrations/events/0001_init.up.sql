-- events.db v1: persisted events for the timeline and WebSocket replay.
-- AUTOINCREMENT so a seq is never reused (clients resume with ?since_seq=).
CREATE TABLE events (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    id             TEXT NOT NULL UNIQUE,
    ts             TEXT NOT NULL,
    type           TEXT NOT NULL,
    source         TEXT NOT NULL,
    actor          TEXT NOT NULL,
    subject_type   TEXT,
    subject_id     TEXT,
    correlation_id TEXT,
    causation_id   TEXT,
    payload        TEXT NOT NULL DEFAULT '{}',
    v              INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX events_ts ON events (ts);
CREATE INDEX events_type_ts ON events (type, ts);
CREATE INDEX events_subject ON events (subject_id);
CREATE INDEX events_correlation ON events (correlation_id);
