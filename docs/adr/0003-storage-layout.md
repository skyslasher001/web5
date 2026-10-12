# 0003 — Storage layout: vault files, three SQLite files, LanceDB, no ORM

- Status: Proposed
- Date: 2026-10-12
- Flags: privacy, architecture

## Context

SPEC §3.5 and §5: the vault is plain files in open formats, usable without the app. Originals are never modified. Deletion is real. SQLite in WAL mode for metadata and FTS5, and a vector store whose rows record which model produced them.

## Decision

- **Vault root** (outside the repo, user-chosen): `<type>/<yyyy>/<mm>/<file>`. Notes are Markdown with YAML frontmatter. Non-text items get `<file>.universe.json` sidecars. The app index lives in `.universe/` (a dot-folder that Obsidian ignores).
- **Three SQLite files** in `.universe/`:
  - `universe.db` — items, versions, chunks + FTS5, links, projects, tags, memories, tasks, approvals, jobs…
  - `events.db` — persisted events (high write rate, isolated from the main DB's writer lock).
  - `audit.db` — append-only (`BEFORE UPDATE/DELETE` triggers abort), hash-chained, written only by the protected audit writer. It stores ids and hashes, never vault content.
- **LanceDB** in `.universe/vectors/`, with one table per (kind, model, version) so re-embedding is a background build and an atomic switch.
- **No ORM:** stdlib `sqlite3`, hand-written SQL in small repository modules, Pydantic models at the API edge, and numbered `up`/`down` SQL migrations each with a test.
- Notes: the file is the source of truth. Other items: the DB is the source of truth and the sidecar mirrors it. "Rebuild index from vault" reconstructs the DB from files and sidecars.

## Consequences

- The vault opens in Obsidian or Explorer with the app closed. Backups are just files.
- Deletion must purge files, versions, sidecars, thumbnails, FTS rows, vectors in every table, caches and traces. A single purge routine plus a test enforces it.
- Splitting the DBs means no cross-file transactions. Events are idempotent and keyed by id, so at-least-once delivery is fine.

## Alternatives considered

- **SQLAlchemy/Alembic:** heavy for SQLite-specific features (FTS5 external content, triggers, `RETURNING`).
- **Chroma:** Apache-2.0, also embedded, but LanceDB's columnar prefilters and on-disk indexes fit 50k items × many chunks better.
- **Single DB file:** simpler, but event writes would contend with ingestion, and the audit log couldn't be protected separately.
