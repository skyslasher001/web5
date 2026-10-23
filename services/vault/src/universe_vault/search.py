"""Hybrid search (SPEC §6, ARCHITECTURE.md §1.4): FTS5 BM25 over titles and text, a trigram index for
fragments, LanceDB vectors for meaning, fused with reciprocal-rank fusion and boosted by pins, use and
recency. The cross-encoder reranker slots in after fusion once the models service exists (ADR-0010).
"""

import math
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from universe_vault import store
from universe_vault.layout import Vault
from universe_vault.query import terms
from universe_vault.schemas import ParsedQuery, SearchHit, SearchResponse
from universe_vault.store import ItemFilters
from universe_vault.vectors import VectorStore

RRF_K = 60
WEIGHTS = {"title": 1.6, "text": 1.0, "trigram": 0.6, "vector": 1.0}
KEYWORD_LIMIT = 200
CHUNK_LIMIT = 400
VECTOR_LIMIT = 150
# A nearest-neighbour search always returns something. A chunk only counts as "related in meaning" when it
# has positive cosine similarity and is not far behind the best match (model-agnostic; ADR-0010).
VECTOR_MAX_DISTANCE = 1.0
VECTOR_MARGIN = 0.25
MARK_START, MARK_END = "«", "»"  # « » around matches in snippets; the UI turns them into <mark>

Match = Literal["title", "text", "trigram", "vector"]


@dataclass
class Filters:
    types: Sequence[str] = ()
    project_id: str | None = None
    tag: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    status: str | None = None


@dataclass
class _Candidate:
    item_id: str
    score: float = 0.0
    matched: list[Match] = field(default_factory=list)
    snippet: str | None = None
    chunk_id: int | None = None


def fts_query(text: str, *, prefix_last: bool = True) -> str | None:
    words = terms(text)
    if not words:
        return None
    quoted = [f'"{w}"' for w in words]
    if prefix_last and len(words[-1]) >= 2:
        quoted[-1] = f'"{words[-1]}"*'
    return " OR ".join(quoted)


def trigram_query(text: str) -> str | None:
    words = [w for w in terms(text) if len(w) >= 3]
    return " OR ".join(f'"{w}"' for w in words) if words else None


def merge_filters(parsed: ParsedQuery, explicit: Filters) -> ItemFilters:
    return ItemFilters(
        types=list(explicit.types) or list(parsed.types),
        project_id=explicit.project_id or (parsed.project_ids[0] if parsed.project_ids else None),
        tag=explicit.tag,
        status=explicit.status,
        date_from=explicit.date_from or parsed.date_from,
        date_to=explicit.date_to or parsed.date_to,
    )


def _ranked(rows: Sequence[sqlite3.Row]) -> list[tuple[str, sqlite3.Row]]:
    """First (best) row per item, in rank order."""
    seen: dict[str, sqlite3.Row] = {}
    for row in rows:
        seen.setdefault(row["item_id"], row)
    return list(seen.items())


def keyword_lists(
    conn: sqlite3.Connection, text: str, filters: ItemFilters
) -> dict[Match, list[tuple[str, sqlite3.Row]]]:
    where, params = store.filter_sql(filters, "i")
    lists: dict[Match, list[tuple[str, sqlite3.Row]]] = {}
    match = fts_query(text)
    if match:
        lists["title"] = _ranked(
            conn.execute(
                "SELECT f.item_id, bm25(items_fts, 0.0, 10.0, 4.0, 2.0) AS rank FROM items_fts f"  # noqa: S608
                f" JOIN items i ON i.id = f.item_id WHERE items_fts MATCH ? AND {where} ORDER BY rank LIMIT ?",
                (match, *params, KEYWORD_LIMIT),
            ).fetchall()
        )
        lists["text"] = _ranked(
            conn.execute(
                "SELECT c.item_id, c.id AS chunk_id, bm25(chunks_fts) AS rank,"  # noqa: S608
                f" snippet(chunks_fts, 0, '{MARK_START}', '{MARK_END}', '…', 18) AS snippet"
                " FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid JOIN items i ON i.id = c.item_id"
                f" WHERE chunks_fts MATCH ? AND {where} ORDER BY rank LIMIT ?",
                (match, *params, CHUNK_LIMIT),
            ).fetchall()
        )
    tri = trigram_query(text)
    if tri:
        lists["trigram"] = _ranked(
            conn.execute(
                "SELECT t.item_id, bm25(items_trigram) AS rank FROM items_trigram t"  # noqa: S608
                f" JOIN items i ON i.id = t.item_id WHERE items_trigram MATCH ? AND {where} ORDER BY rank LIMIT ?",
                (tri, *params, KEYWORD_LIMIT),
            ).fetchall()
        )
    return lists


def vector_list(
    conn: sqlite3.Connection,
    vectors: VectorStore,
    table: str,
    vector: list[float],
    filters: ItemFilters,
) -> list[tuple[str, int, float]]:
    hits = vectors.search(
        table,
        vector,
        limit=VECTOR_LIMIT,
        types=list(filters.types) or None,
        date_from=filters.date_from,
        date_to=filters.date_to,
    )
    if not hits:
        return []
    cutoff = min(VECTOR_MAX_DISTANCE, min(h.distance for h in hits) + VECTOR_MARGIN)
    best: dict[str, tuple[int, float]] = {}
    for hit in hits:
        if hit.distance >= cutoff:
            continue
        if hit.item_id not in best or hit.distance < best[hit.item_id][1]:
            best[hit.item_id] = (hit.chunk_id, hit.distance)
    if not best:
        return []
    # Project, tag, status and trash filters live in SQLite: keep only candidates that pass them.
    where, params = store.filter_sql(filters, "i")
    ids = list(best)
    marks = ",".join("?" * len(ids))
    allowed = {
        row["id"]
        for row in conn.execute(f"SELECT i.id FROM items i WHERE i.id IN ({marks}) AND {where}", (*ids, *params))  # noqa: S608
    }
    ranked = sorted(((i, c, d) for i, (c, d) in best.items() if i in allowed), key=lambda x: x[2])
    return ranked


def _boost(row: sqlite3.Row, now: datetime) -> float:
    factor = 1.0
    if row["pinned"]:
        factor *= 1.15
    factor *= 1.0 + 0.05 * math.log1p(row["open_count"] or 0)
    try:
        captured = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
        age_days = max(0.0, (now - captured).total_seconds() / 86400)
        factor *= 1.0 + 0.08 * math.exp(-age_days / 90)
    except (ValueError, AttributeError):
        pass
    return factor


def _excerpt(conn: sqlite3.Connection, chunk_id: int, text: str) -> str | None:
    row = conn.execute("SELECT item_id, kind, text FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    if row is None:
        return None
    if row["kind"] == "metadata":
        # The metadata chunk ("title, type, camera…") helps matching but reads badly: show real content.
        row = conn.execute(
            "SELECT text FROM chunks WHERE item_id = ? AND kind != 'metadata' ORDER BY ord, id LIMIT 1",
            (row["item_id"],),
        ).fetchone()
        if row is None:
            return None
    body: str = row["text"]
    words = terms(text)
    lowered = body.lower()
    pos = min((lowered.find(w) for w in words if lowered.find(w) >= 0), default=0)
    start = max(0, pos - 60)
    snippet = body[start : start + 220].replace("\n", " ").strip()
    return ("…" if start else "") + snippet + ("…" if start + 220 < len(body) else "")


def search(
    conn: sqlite3.Connection,
    vault: Vault,
    parsed: ParsedQuery,
    explicit: Filters,
    *,
    vectors: VectorStore | None = None,
    vector: list[float] | None = None,
    vector_table: str | None = None,
    limit: int = 30,
    semantic_note: str | None = None,
    query: str = "",
) -> SearchResponse:
    started = time.perf_counter()
    timings: dict[str, float] = {}
    filters = merge_filters(parsed, explicit)
    text = parsed.text
    semantic = bool(vector and vectors and vector_table)
    candidates: dict[str, _Candidate] = {}

    if not terms(text) and not semantic:
        # Only filters (e.g. "photos from last summer"): browse, newest first.
        page = store.list_items(conn, vault, filters, sort="captured", limit=limit)
        hits = [SearchHit(item=s, score=0.0) for s in page.items]
        return SearchResponse(
            query=query,
            mode="keyword",
            semantic=False,
            semantic_note=semantic_note,
            parsed=parsed,
            hits=hits,
            took_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    t0 = time.perf_counter()
    lists = keyword_lists(conn, text, filters) if terms(text) else {}
    timings["keyword"] = round((time.perf_counter() - t0) * 1000, 2)
    for kind, ranked in lists.items():
        for rank, (item_id, row) in enumerate(ranked):
            cand = candidates.setdefault(item_id, _Candidate(item_id))
            cand.score += WEIGHTS[kind] / (RRF_K + rank + 1)
            cand.matched.append(kind)
            if kind == "text" and cand.snippet is None:
                cand.snippet = row["snippet"]
    if semantic and vectors and vector and vector_table:
        t0 = time.perf_counter()
        ranked_vec = vector_list(conn, vectors, vector_table, vector, filters)
        timings["vector"] = round((time.perf_counter() - t0) * 1000, 2)
        for rank, (item_id, chunk_id, _distance) in enumerate(ranked_vec):
            cand = candidates.setdefault(item_id, _Candidate(item_id))
            cand.score += WEIGHTS["vector"] / (RRF_K + rank + 1)
            cand.matched.append("vector")
            if cand.chunk_id is None:
                cand.chunk_id = chunk_id

    if candidates:
        ids = list(candidates)
        marks = ",".join("?" * len(ids))
        rows = {
            r["id"]: r
            for r in conn.execute(
                f"SELECT id, pinned, open_count, captured_at FROM items WHERE id IN ({marks})",  # noqa: S608
                tuple(ids),
            )
        }
        now = datetime.now(UTC)
        for cand in candidates.values():
            if cand.item_id in rows:
                cand.score *= _boost(rows[cand.item_id], now)
    top = sorted(candidates.values(), key=lambda c: c.score, reverse=True)[:limit]
    summaries = store.summaries_by_id(conn, vault, [c.item_id for c in top])
    hits = []
    for cand in top:
        summary = summaries.get(cand.item_id)
        if summary is None:
            continue
        snippet = cand.snippet
        if snippet is None and cand.chunk_id is not None:
            snippet = _excerpt(conn, cand.chunk_id, text)
        hits.append(SearchHit(item=summary, score=round(cand.score, 6), snippet=snippet, matched=cand.matched))
    return SearchResponse(
        query=query,
        mode="hybrid" if semantic else "keyword",
        semantic=semantic,
        semantic_note=semantic_note,
        parsed=parsed,
        hits=hits,
        took_ms=round((time.perf_counter() - started) * 1000, 2),
        timings_ms=timings,
    )
