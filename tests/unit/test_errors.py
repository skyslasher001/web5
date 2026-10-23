from pathlib import Path

from universe_common.errors import capture_exception, fingerprint_from_text
from universe_common.sqlite import connect, migrate_up
from universe_core.db import migrations_dir
from universe_core.errors import ErrorStore
from universe_core.events import EventBus


def _boom(message: str) -> None:
    raise ValueError(message)


def _capture(message: str):
    try:
        _boom(message)
    except ValueError as exc:
        return capture_exception(exc)
    raise AssertionError("unreachable")


def test_same_location_groups_even_with_different_messages() -> None:
    a, b = _capture("parcel 1 failed"), _capture("parcel 2 failed")
    assert a.fingerprint == b.fingerprint
    assert a.kind == "ValueError"
    assert "parcel 1 failed" in a.stack


def test_text_fingerprint_ignores_volatile_numbers() -> None:
    stack1 = "TypeError: x\n    at render (app.js:10:5)\n    at 0x7ff12"
    stack2 = "TypeError: x\n    at render (app.js:99:7)\n    at 0x7ff99"
    assert fingerprint_from_text("TypeError", "x", stack1) == fingerprint_from_text("TypeError", "x", stack2)


def test_store_upserts_by_fingerprint_and_emits_events(tmp_path: Path) -> None:
    conn = connect(tmp_path / "u.db")
    migrate_up(conn, migrations_dir("universe"))
    events = connect(tmp_path / "e.db")
    migrate_up(events, migrations_dir("events"))
    bus = EventBus(events)
    store = ErrorStore(conn, bus)
    records = [
        store.record(service="core", kind="ValueError", message="m", stack="s", fingerprint="fp1") for _ in range(3)
    ]
    record = records[-1]
    assert record is not None and record.count == 3
    assert len(store.list()) == 1
    assert [e.payload["count"] for e in bus.replay(0, types=["error.raised"])] == [1, 2, 3]
