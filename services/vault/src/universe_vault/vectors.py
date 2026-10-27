"""Text vectors in LanceDB (`.universe/vectors/`): one table per (embedding model, digest) (ADR-0003).

The table name records which model produced every vector in it. Switching models builds a new table in
the background while search keeps using keyword matches for items not yet re-embedded.
"""

import re
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

TABLE_PREFIX = "text__"


@dataclass(frozen=True)
class VectorRow:
    chunk_id: int
    item_id: str
    item_type: str
    captured_at: str
    vector: list[float]


@dataclass(frozen=True)
class VectorHit:
    item_id: str
    chunk_id: int
    distance: float


def table_name(model: str, digest: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")[:60]
    return f"{TABLE_PREFIX}{slug}__{(digest or 'nodigest')[:12]}"


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class VectorStore:
    """Thread-safe enough for our use: one handle per table, opened lazily, reads see other processes' writes."""

    def __init__(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(path), read_consistency_interval=timedelta(0))
        self._tables: dict[str, Any] = {}
        self._lock = threading.Lock()

    def names(self) -> list[str]:
        result: Any = self._db.list_tables()  # a response object with .tables in current LanceDB
        names: list[Any] = list(getattr(result, "tables", result))
        return [n for n in names if isinstance(n, str) and n.startswith(TABLE_PREFIX)]

    def _open(self, name: str, dim: int | None = None) -> Any:
        with self._lock:
            table = self._tables.get(name)
            if table is not None:
                return table
            if name in self.names():
                table = self._db.open_table(name)
            elif dim is not None:
                schema = pa.schema(
                    [
                        pa.field("chunk_id", pa.int64()),
                        pa.field("item_id", pa.string()),
                        pa.field("item_type", pa.string()),
                        pa.field("captured_at", pa.string()),
                        pa.field("vector", pa.list_(pa.float32(), dim)),
                    ]
                )
                table = self._db.create_table(name, schema=schema, exist_ok=True)
            else:
                return None
            self._tables[name] = table
            return table

    def replace_item(self, name: str, item_id: str, rows: list[VectorRow]) -> None:
        if not rows:
            self.delete_item(item_id, only=name)
            return
        table = self._open(name, dim=len(rows[0].vector))
        table.delete(f"item_id = {_quote(item_id)}")
        table.add(
            [
                {
                    "chunk_id": r.chunk_id,
                    "item_id": r.item_id,
                    "item_type": r.item_type,
                    "captured_at": r.captured_at,
                    "vector": r.vector,
                }
                for r in rows
            ]
        )

    def add_many(self, name: str, rows: list[VectorRow], *, batch: int = 5000) -> None:
        """Append rows in bulk (seed data; the pipeline uses replace_item per item)."""
        if not rows:
            return
        table = self._open(name, dim=len(rows[0].vector))
        for start in range(0, len(rows), batch):
            table.add(
                [
                    {
                        "chunk_id": r.chunk_id,
                        "item_id": r.item_id,
                        "item_type": r.item_type,
                        "captured_at": r.captured_at,
                        "vector": r.vector,
                    }
                    for r in rows[start : start + batch]
                ]
            )

    def delete_item(self, item_id: str, *, only: str | None = None) -> None:
        for name in [only] if only else self.names():
            table = self._open(name)
            if table is not None:
                table.delete(f"item_id = {_quote(item_id)}")

    def count(self, name: str, item_id: str | None = None) -> int:
        table = self._open(name)
        if table is None:
            return 0
        return int(table.count_rows(f"item_id = {_quote(item_id)}" if item_id else None))

    def search(
        self,
        name: str,
        vector: list[float],
        *,
        limit: int = 200,
        types: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[VectorHit]:
        table = self._open(name)
        if table is None:
            return []
        query = table.search(vector).metric("cosine").limit(limit)
        clauses = []
        if types:
            clauses.append(f"item_type IN ({', '.join(_quote(t) for t in types)})")
        if date_from:
            clauses.append(f"captured_at >= {_quote(date_from)}")
        if date_to:
            clauses.append(f"captured_at < {_quote(date_to)}")
        if clauses:
            query = query.where(" AND ".join(clauses), prefilter=True)
        return [
            VectorHit(item_id=r["item_id"], chunk_id=int(r["chunk_id"]), distance=float(r["_distance"]))
            for r in query.select(["item_id", "chunk_id", "_distance"]).to_list()
        ]

    def item_mean(self, name: str, item_id: str) -> list[float] | None:
        """One item's mean chunk vector (for "similar items"), or None if it has no vectors in this table."""
        table = self._open(name)
        if table is None:
            return None
        rows = table.search().where(f"item_id = {_quote(item_id)}").select(["vector"]).limit(10_000).to_list()
        if not rows:
            return None
        width = len(rows[0]["vector"])
        return [sum(float(r["vector"][k]) for r in rows) / len(rows) for k in range(width)]

    def item_means(self, name: str, *, batch_rows: int = 8192) -> tuple[list[str], Any]:
        """Each item's mean chunk vector as (sorted ids, float32 matrix), streamed in batches: a big vault's
        vectors don't fit in memory at once."""
        import numpy as np

        table = self._open(name)
        total = int(table.count_rows()) if table is not None else 0
        if table is None or total == 0:
            return [], np.zeros((0, 0), dtype=np.float32)
        # The ids first (cheap), so the sums are one float32 matrix in sorted-id order, allocated once and
        # averaged in place. A Python loop over 50k rows, each its own float64 copy, took 9 of the layout job's
        # 14 s, and about five times that on CI's Windows runner (2026-10-27).
        scan = table.search().limit(total)
        ids = sorted({i for b in scan.select(["item_id"]).to_batches(batch_rows) for i in b.column(0).to_pylist()})
        index = {item_id: n for n, item_id in enumerate(ids)}
        sums: Any = None
        counts = np.zeros(len(ids), dtype=np.int64)
        for batch in table.search().select(["item_id", "vector"]).limit(total).to_batches(batch_rows):
            vectors = batch.column("vector")
            width = vectors.type.list_size
            rows = np.fromiter((index[i] for i in batch.column("item_id").to_pylist()), np.int64, len(batch))
            if sums is None:
                sums = np.zeros((len(ids), width), dtype=np.float32)
            np.add.at(sums, rows, vectors.flatten().to_numpy(zero_copy_only=False).reshape(len(rows), width))
            counts += np.bincount(rows, minlength=len(ids))
        sums /= counts[:, None]
        return ids, sums

    def drop(self, name: str) -> None:
        with self._lock:
            self._tables.pop(name, None)
        if name in self.names():
            self._db.drop_table(name)
