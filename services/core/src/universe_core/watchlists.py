"""Watchlists (Phase 6, ADR-0015): re-run a saved topic or page on a schedule and record what changed.

Every check goes through the egress gate, so offline mode and the kill switch stop it (a blocked cycle simply
waits for next time). Change summaries land in `watchlist_hits` and surface in the Research panel; the morning
brief that will carry them is Phase 9. Web content is untrusted and stored as-is for the owner to read.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from contextlib import suppress
from typing import TYPE_CHECKING

from universe_common.egress import EgressDenied
from universe_common.ids import uuid7
from universe_common.log import get_logger
from universe_common.timeutil import utcnow
from universe_core.research_tools import run_search
from universe_research.fetch import fetch_page

if TYPE_CHECKING:
    from universe_core.context import CoreContext

log = get_logger(__name__)


def fingerprint(parts: list[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


class WatchlistStore:
    """Synchronous data access over universe.db (used by the API handlers and the runner)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM watchlists ORDER BY created_at DESC").fetchall()

    def get(self, wid: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM watchlists WHERE id = ?", (wid,)).fetchone()

    def create(self, *, kind: str, target: str, label: str, interval_s: int) -> sqlite3.Row:
        wid = uuid7()
        self._conn.execute(
            "INSERT INTO watchlists (id, kind, target, label, interval_s, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (wid, kind, target, label, interval_s, utcnow()),
        )
        row = self.get(wid)
        assert row is not None
        return row

    def delete(self, wid: str) -> bool:
        return bool(self._conn.execute("DELETE FROM watchlists WHERE id = ?", (wid,)).rowcount)

    def set_enabled(self, wid: str, enabled: bool) -> sqlite3.Row | None:
        self._conn.execute("UPDATE watchlists SET enabled = ? WHERE id = ?", (int(enabled), wid))
        return self.get(wid)

    def due(self, now_iso: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM watchlists WHERE enabled = 1 AND (last_checked_at IS NULL OR "
            "(julianday(?) - julianday(last_checked_at)) * 86400.0 >= interval_s)",
            (now_iso,),
        ).fetchall()

    def record(self, wid: str, fp: str, summary: str, checked_at: str, *, hit: bool, detail: str) -> None:
        self._conn.execute(
            "UPDATE watchlists SET last_checked_at = ?, last_fingerprint = ?, last_summary = ? WHERE id = ?",
            (checked_at, fp, summary, wid),
        )
        if hit:
            self._conn.execute(
                "INSERT INTO watchlist_hits (id, watchlist_id, found_at, summary, detail, seen) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (uuid7(), wid, checked_at, summary, detail),
            )

    def hits(self, wid: str, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM watchlist_hits WHERE watchlist_id = ? ORDER BY found_at DESC LIMIT ?", (wid, limit)
        ).fetchall()

    def unseen_count(self, wid: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM watchlist_hits WHERE watchlist_id = ? AND seen = 0", (wid,)
        ).fetchone()
        return int(row["n"])

    def mark_seen(self, wid: str) -> None:
        self._conn.execute("UPDATE watchlist_hits SET seen = 1 WHERE watchlist_id = ?", (wid,))


async def check_one(ctx: CoreContext, store: WatchlistStore, row: sqlite3.Row) -> bool:
    """Re-run one watchlist, record the result, and return whether it changed since last time."""
    target = row["target"]
    checked_at = utcnow()
    if row["kind"] == "topic":
        results = await run_search(ctx, "agent:researcher", target, 8, use_cache=False)
        fp = fingerprint([r.url for r in results])
        summary = f"{len(results)} result(s); top: {results[0].title}" if results else "no results"
        detail = "\n".join(f"- {r.title} — {r.url}" for r in results[:8])
    else:
        async with ctx.gate.async_client(purpose="research:watch", actor="agent:researcher") as client:
            page = await fetch_page(client, target, max_chars=20_000)
        fp = fingerprint([page.text])
        summary = f"Page updated: {page.title}"
        detail = page.text[:800]
    changed = row["last_fingerprint"] is not None and fp != row["last_fingerprint"]
    store.record(row["id"], fp, summary, checked_at, hit=changed, detail=detail if changed else "")
    if changed:
        ctx.bus.publish(
            "research.watchlist.changed",
            {"watchlist_id": row["id"], "label": row["label"] or target, "summary": summary},
            actor="agent:researcher",
            subject_type="watchlist",
            subject_id=row["id"],
        )
    return changed


class WatchlistRunner:
    """A background loop that checks due watchlists. Best-effort; failures become issues, not crashes."""

    TICK_S = 300.0

    def __init__(self, ctx: CoreContext) -> None:
        self.ctx = ctx
        self.store = WatchlistStore(ctx.dbs.universe)
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="watchlists")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.check_due()
            except Exception as exc:  # a bad cycle must not kill the loop
                self.ctx.record_exception(exc)
            await asyncio.sleep(self.TICK_S)

    async def check_due(self) -> int:
        changed = 0
        for row in self.store.due(utcnow()):
            try:
                if await check_one(self.ctx, self.store, row):
                    changed += 1
            except EgressDenied:
                break  # offline or kill switch: stop this cycle and try again next time
            except Exception as exc:
                self.ctx.record_exception(exc)
        return changed
