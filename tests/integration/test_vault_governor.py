"""The governor loop: model jobs wait while you chat, embedding-model changes trigger re-embedding,
housekeeping empties expired trash, and pause/resume transitions are announced."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from universe_common.sqlite import connect
from universe_core.db import Databases
from universe_core.vault_runtime import Governor
from universe_vault import governor, ingest, purge
from universe_vault.layout import Vault
from universe_vault.models import ModelInfo


@pytest.fixture
def conn_and_vault(tmp_path: Path) -> Iterator[tuple[sqlite3.Connection, Vault]]:
    vault = Vault(tmp_path / "vault")
    vault.ensure()
    Databases.open(vault.index).close()
    conn = connect(vault.db_path)
    yield conn, vault
    conn.close()


class Stub:
    def __init__(self) -> None:
        self.chats = 0
        self.embedder: ModelInfo | None = None
        self.purged: list[str] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.battery: Any = None  # no battery, like a desktop

    async def current_embedder(self) -> ModelInfo | None:
        return self.embedder

    async def purge(self, item_id: str) -> bool:
        self.purged.append(item_id)
        return True


def make(conn: sqlite3.Connection, vault: Vault, stub: Stub) -> Governor:
    return Governor(
        conn=conn,
        vault=vault,
        chat_active=lambda: stub.chats,
        current_embedder=stub.current_embedder,
        purge_item=stub.purge,
        publish=lambda event_type, payload: stub.events.append((event_type, payload)),
        battery=lambda: stub.battery,
    )


def reembed_jobs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'reembed'").fetchone()[0]


async def test_chatting_holds_model_jobs(conn_and_vault: tuple[sqlite3.Connection, Vault]) -> None:
    conn, vault = conn_and_vault
    stub = Stub()
    gov = make(conn, vault, stub)
    await gov.tick(now=0)
    assert not governor.state(conn).model_hold
    stub.chats = 1
    await gov.tick(now=1)
    assert governor.state(conn).model_hold
    assert governor.claim_filter(conn)[1] == ("embed", "caption")


async def test_a_new_or_changed_embedder_queues_reembedding_once(
    conn_and_vault: tuple[sqlite3.Connection, Vault],
) -> None:
    conn, vault = conn_and_vault
    stub = Stub()
    gov = make(conn, vault, stub)
    await gov.check_embedder()
    assert reembed_jobs(conn) == 0  # nothing installed yet
    stub.embedder = ModelInfo("nomic-embed-text:latest", "d1", ("embedding",))
    await gov.check_embedder()
    await gov.check_embedder()
    assert reembed_jobs(conn) == 1
    conn.execute("UPDATE jobs SET status = 'succeeded', idempotency_key = NULL")
    stub.embedder = ModelInfo("nomic-embed-text:latest", "d2", ("embedding",))  # model updated
    await gov.check_embedder()
    assert reembed_jobs(conn) == 2


async def test_housekeeping_purges_expired_trash(conn_and_vault: tuple[sqlite3.Connection, Vault]) -> None:
    conn, vault = conn_and_vault
    stub = Stub()
    old = ingest.create_note(conn, vault, "old trash")
    fresh = ingest.create_note(conn, vault, "fresh trash")
    purge.trash(conn, vault, old)
    purge.trash(conn, vault, fresh)
    conn.execute("UPDATE items SET trashed_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (old,))
    await make(conn, vault, stub).housekeeping()
    assert stub.purged == [old]


async def test_pause_transitions_are_announced(conn_and_vault: tuple[sqlite3.Connection, Vault]) -> None:
    conn, vault = conn_and_vault
    stub = Stub()
    gov = make(conn, vault, stub)
    await gov.tick(now=0)
    governor.set_paused(conn, True, "paused by you")
    await gov.tick(now=1)
    governor.set_paused(conn, False)
    await gov.tick(now=2)
    assert [e[0] for e in stub.events] == ["governor.paused", "governor.resumed"]


async def test_battery_pauses_and_power_resumes(conn_and_vault: tuple[sqlite3.Connection, Vault]) -> None:
    conn, vault = conn_and_vault
    stub = Stub()
    gov = make(conn, vault, stub)
    stub.battery = SimpleNamespace(power_plugged=False, percent=80)
    await gov.tick(now=0)
    assert governor.state(conn).paused and governor.state(conn).reason == "battery"
    stub.battery = SimpleNamespace(power_plugged=True, percent=81)
    await gov.tick(now=1)
    assert not governor.state(conn).paused
    governor.set_paused(conn, True, "paused by you")  # plugging in never overrides your own pause
    stub.battery = SimpleNamespace(power_plugged=True, percent=90)
    await gov.tick(now=2)
    assert governor.state(conn).reason == "paused by you"
