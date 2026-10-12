# 0002 — Custom SQLite job queue instead of huey

- Status: Accepted (2026-10-12)
- Date: 2026-10-12
- Flags: architecture

## Context

SPEC §22 suggests a SQLite-backed queue "e.g. huey", with no Redis. The ingestion pipeline is a per-item DAG of up to 12 stages. It must be prioritized (realtime > interactive > background), pausable by the performance governor, resumable after crashes, visible per item in the UI, and re-runnable when a model is upgraded.

## Decision

A `jobs` table in `universe.db`, plus a small lease loop (~300 lines):

- Claim: `UPDATE jobs SET status='leased', lease_owner=?, lease_expires_at=? WHERE id = (SELECT id FROM jobs WHERE status='queued' AND run_after<=? AND priority_class IN (…allowed by governor…) AND deps satisfied ORDER BY priority DESC, id LIMIT 1) RETURNING *`.
- Leases are renewed while a job runs. An expired lease puts the job back to `queued` (crash safety).
- Retries use exponential backoff with jitter. After `max_attempts` the job goes `dead` and is reported to Forge.
- An `idempotency_key` (item + stage + model version) prevents duplicate work. Model upgrades re-enqueue stale stages.
- Progress and state changes are published as events.

## Consequences

- One source of truth for job state, joinable with `items` and `item_stages` for the UI.
- The governor controls exactly which priority classes may be claimed.
- We own ~300 lines of code plus its tests (unit tests for lease expiry, retry and dependency ordering).

## Alternatives considered

- **huey (SqliteHuey):** MIT and mature, but it keeps its own task storage separate from our item state. Priorities exist, but governor-driven pausing, per-item DAG dependencies and stage-level progress would all be built around it anyway.
- **Celery/RQ/Dramatiq:** need Redis or RabbitMQ, which is excluded by the spec.
