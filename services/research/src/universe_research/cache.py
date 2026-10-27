"""A TTL cache for search results and fetched pages (ADR-0015).

Pure over a sqlite connection (the caller passes Core's `universe.db`; the tables come from migration 0008).
Caching saves time, tokens and repeat requests, and makes a saved report reproducible. Rows older than the TTL
read as a miss and are swept on write. The connection must use `sqlite3.Row` as its row factory.
"""

import json
import sqlite3
import time
from collections.abc import Callable

from universe_research.fetch import FetchedPage
from universe_research.providers import SearchResult

DEFAULT_TTL_S = 24 * 60 * 60  # a day


class ResearchCache:
    def __init__(
        self, conn: sqlite3.Connection, *, ttl_s: int = DEFAULT_TTL_S, now: Callable[[], float] = time.time
    ) -> None:
        self._conn = conn
        self.ttl_s = ttl_s
        self._now = now

    def _fresh(self, fetched_at: float) -> bool:
        return float(fetched_at) >= self._now() - self.ttl_s

    def get_search(self, provider: str, query: str) -> list[SearchResult] | None:
        row = self._conn.execute(
            "SELECT results, fetched_at FROM research_search_cache WHERE provider = ? AND query = ?",
            (provider, query),
        ).fetchone()
        if row is None or not self._fresh(row["fetched_at"]):
            return None
        return [SearchResult.from_dict(d) for d in json.loads(row["results"])]

    def put_search(self, provider: str, query: str, results: list[SearchResult]) -> None:
        self._conn.execute(
            "INSERT INTO research_search_cache (provider, query, results, fetched_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(provider, query) DO UPDATE SET results = excluded.results, fetched_at = excluded.fetched_at",
            (provider, query, json.dumps([r.to_dict() for r in results]), self._now()),
        )
        self.purge_expired()

    def get_page(self, url: str) -> FetchedPage | None:
        row = self._conn.execute(
            "SELECT url, title, text, status, fetched_at, truncated FROM research_page_cache WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None or not self._fresh(row["fetched_at"]):
            return None
        return FetchedPage(
            url=row["url"],
            title=row["title"],
            text=row["text"],
            status=row["status"],
            fetched_at=row["fetched_at"],
            truncated=bool(row["truncated"]),
        )

    def put_page(self, page: FetchedPage) -> None:
        self._conn.execute(
            "INSERT INTO research_page_cache (url, title, text, status, fetched_at, truncated) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(url) DO UPDATE SET "
            "title = excluded.title, text = excluded.text, status = excluded.status, "
            "fetched_at = excluded.fetched_at, truncated = excluded.truncated",
            (page.url, page.title, page.text, page.status, page.fetched_at, int(page.truncated)),
        )
        self.purge_expired()

    def purge_expired(self) -> None:
        cutoff = self._now() - self.ttl_s
        self._conn.execute("DELETE FROM research_search_cache WHERE fetched_at < ?", (cutoff,))
        self._conn.execute("DELETE FROM research_page_cache WHERE fetched_at < ?", (cutoff,))
