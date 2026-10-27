"""VaultDb (Core's thread-per-call access to the vault database) at shutdown."""

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from universe_core.vault_runtime import VaultDb


def test_close_waits_for_a_call_still_running_and_refuses_new_ones(tmp_path: Path) -> None:
    """Regression: a cancelled governor tick left its query running in a thread, and close() closed that
    thread's connection mid-query, crashing the process (a segfault in SQLite at shutdown)."""
    db = VaultDb(tmp_path / "v.db")
    started = threading.Event()
    finished: list[int] = []

    def slow(conn: sqlite3.Connection) -> int:
        started.set()
        time.sleep(0.3)
        value = conn.execute("SELECT 41 + 1").fetchone()[0]  # the connection must still be open here
        finished.append(value)
        return value

    async def main() -> None:
        task = asyncio.create_task(db.run(slow))
        await asyncio.to_thread(started.wait)
        task.cancel()  # what Governor.stop() does: the await ends, the thread doesn't
        t0 = time.monotonic()
        await asyncio.to_thread(db.close)
        assert time.monotonic() - t0 >= 0.2  # it waited for the query
        assert finished == [42]
        with pytest.raises(RuntimeError, match="closed"):
            await db.run(lambda conn: conn.execute("SELECT 1").fetchone())

    asyncio.run(main())
