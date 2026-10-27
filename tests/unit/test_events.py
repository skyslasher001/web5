from pathlib import Path

import pytest

from universe_common.sqlite import connect, migrate_up
from universe_core.db import migrations_dir
from universe_core.events import CATALOG, EventBus, UnknownEventType


@pytest.fixture
def bus(tmp_path: Path) -> EventBus:
    conn = connect(tmp_path / "events.db")
    migrate_up(conn, migrations_dir("events"))
    return EventBus(conn)


async def test_persisted_events_get_a_seq_and_live_ones_do_not(bus: EventBus) -> None:
    stored = bus.publish("chat.message", {"x": 1}, subject_type="conversation", subject_id="c1")
    live = bus.publish("chat.token", {"delta": "hi"})
    assert stored.seq == 1
    assert live.seq is None
    assert [e.type for e in bus.replay(0)] == ["chat.message"]
    assert bus.last_seq() == 1


async def test_unknown_event_types_are_rejected(bus: EventBus) -> None:
    with pytest.raises(UnknownEventType):
        bus.publish("chat.tokne")


async def test_subscriptions_match_glob_patterns(bus: EventBus) -> None:
    chat = bus.subscribe(["chat.*"])
    everything = bus.subscribe(["*"])
    bus.publish("chat.token", {"delta": "a"})
    bus.publish("service.started", {"service": "core"})
    assert chat.queue.qsize() == 1
    assert everything.queue.qsize() == 2
    bus.unsubscribe(chat)
    bus.publish("chat.token", {"delta": "b"})
    assert chat.queue.qsize() == 1


async def test_a_full_subscriber_is_flagged_not_blocking(bus: EventBus) -> None:
    sub = bus.subscribe(["*"])
    sub.queue = type(sub.queue)(maxsize=2)
    for _ in range(3):
        bus.publish("chat.token", {"delta": "x"})
    assert sub.overflowed
    assert sub.queue.qsize() == 2


async def test_replay_filters_by_seq_and_type(bus: EventBus) -> None:
    bus.publish("service.started", {})
    second = bus.publish("chat.message", {})
    bus.publish("error.raised", {})
    assert [e.type for e in bus.replay(1)] == ["chat.message", "error.raised"]
    assert [e.seq for e in bus.replay(0, types=["chat.*"])] == [second.seq]


def test_catalog_names_are_well_formed() -> None:
    for name in CATALOG:
        assert name == name.lower() and "." in name and " " not in name
