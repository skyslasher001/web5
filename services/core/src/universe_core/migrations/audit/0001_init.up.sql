-- audit.db v1: append-only, hash-chained audit log (protected core).
-- hash = sha256(prev_hash || canonical_json(row)). Details hold ids and hashes, never vault content.
CREATE TABLE audit_log (
    seq         INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target_type TEXT,
    target_id   TEXT,
    details     TEXT NOT NULL DEFAULT '{}',
    outcome     TEXT NOT NULL DEFAULT 'ok',
    task_id     TEXT,
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL UNIQUE
);
CREATE INDEX audit_ts ON audit_log (ts);
CREATE INDEX audit_action ON audit_log (action, ts);
CREATE INDEX audit_actor ON audit_log (actor, ts);

CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
