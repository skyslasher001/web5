"""The SQLite job queue: priority, leases, retries with backoff, idempotency and the governor's switches."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from universe_vault import governor, jobs

from universe_common.sqlite import connect
from universe_core.db import Databases


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    Databases.open(tmp_path).close()  # migrate
    c = connect(tmp_path / "universe.db")
    yield c
    c.close()


def test_claims_follow_priority_class_then_priority(conn: sqlite3.Connection) -> None:
    jobs.enqueue(conn, "embed", priority_class="background", priority=50)
    jobs.enqueue(conn, "pipeline", priority_class="interactive", priority=0)
    jobs.enqueue(conn, "import", priority_class="interactive", priority=10)
    kinds = []
    while (job := jobs.claim(conn, "w1")) is not None:
        kinds.append(job.kind)
        jobs.complete(conn, job.id, "w1")
    assert kinds == ["import", "pipeline", "embed"]


def test_a_dead_workers_lease_returns_the_job(conn: sqlite3.Connection) -> None:
    job_id = jobs.enqueue(conn, "pipeline")
    job = jobs.claim(conn, "w1", lease_s=60)
    assert job is not None and job.id == job_id
    assert jobs.claim(conn, "w2") is None  # leased
    conn.execute("UPDATE jobs SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (job_id,))
    again = jobs.claim(conn, "w2")
    assert again is not None and again.id == job_id and again.attempts == 2
    assert not jobs.complete(conn, again.id, "w1")  # the old worker can no longer finish it
    assert jobs.complete(conn, again.id, "w2")


def test_failures_back_off_then_die(conn: sqlite3.Connection) -> None:
    job_id = jobs.enqueue(conn, "embed", max_attempts=2)
    assert job_id is not None
    job = jobs.claim(conn, "w1")
    assert job is not None
    assert jobs.fail(conn, job.id, "w1", "boom") == "queued"
    info = jobs.get(conn, job_id)
    assert info is not None and info.status == "queued" and info.error == "boom"
    assert jobs.claim(conn, "w1") is None  # backing off
    conn.execute("UPDATE jobs SET run_after = '2000-01-01T00:00:00.000Z' WHERE id = ?", (job_id,))
    job = jobs.claim(conn, "w1")
    assert job is not None and job.attempts == 2
    assert jobs.fail(conn, job.id, "w1", "boom again") == "dead"
    assert jobs.retry(conn, job_id)
    assert jobs.claim(conn, "w1") is not None


def test_an_expired_lease_on_the_last_attempt_is_dead(conn: sqlite3.Connection) -> None:
    job_id = jobs.enqueue(conn, "pipeline", max_attempts=1)
    assert jobs.claim(conn, "w1") is not None
    conn.execute("UPDATE jobs SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (job_id,))
    assert jobs.claim(conn, "w2") is None
    info = jobs.get(conn, str(job_id))
    assert info is not None and info.status == "dead"


def test_idempotency_key_reuses_unfinished_work_only(conn: sqlite3.Connection) -> None:
    first = jobs.enqueue(conn, "pipeline", item_id=None, idempotency_key="pipeline:x")
    assert jobs.enqueue(conn, "pipeline", idempotency_key="pipeline:x") == first
    job = jobs.claim(conn, "w1")
    assert job is not None
    jobs.complete(conn, job.id, "w1")
    second = jobs.enqueue(conn, "pipeline", idempotency_key="pipeline:x")
    assert second is not None and second != first


def test_release_does_not_count_an_attempt(conn: sqlite3.Connection) -> None:
    job_id = jobs.enqueue(conn, "embed")
    job = jobs.claim(conn, "w1")
    assert job is not None
    jobs.release(conn, job.id, "w1", delay_s=0)
    info = jobs.get(conn, str(job_id))
    assert info is not None and info.status == "queued" and info.attempts == 0


def test_governor_pause_and_model_hold(conn: sqlite3.Connection) -> None:
    jobs.enqueue(conn, "embed")
    jobs.enqueue(conn, "pipeline")
    governor.set_paused(conn, True, "battery")
    classes, exclude = governor.claim_filter(conn)
    assert jobs.claim(conn, "w1", classes=classes, exclude_kinds=exclude) is None
    assert governor.state(conn).reason == "battery"
    governor.set_paused(conn, False)
    governor.hold_models(conn, 30)
    classes, exclude = governor.claim_filter(conn)
    job = jobs.claim(conn, "w1", classes=classes, exclude_kinds=exclude)
    assert job is not None and job.kind == "pipeline"
    assert jobs.claim(conn, "w1", classes=classes, exclude_kinds=exclude) is None  # embed waits for the chat


def test_stats_and_pruning(conn: sqlite3.Connection) -> None:
    jobs.enqueue(conn, "embed")
    done = jobs.enqueue(conn, "pipeline")
    job = jobs.claim(conn, "w1", exclude_kinds=("embed",))
    assert job is not None and job.id == done
    jobs.complete(conn, job.id, "w1")
    stats = jobs.stats(conn, paused=False, pause_reason=None, model_hold=False, workers=1)
    assert stats.queued == 1 and stats.succeeded_last_hour == 1 and stats.by_kind == {"embed": 1}
    conn.execute("UPDATE jobs SET finished_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (done,))
    assert jobs.prune_finished(conn) == 1
