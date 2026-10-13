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
        sums: dict[str, Any] = {}
        counts: dict[str, int] = {}
        for batch in table.search().select(["item_id", "vector"]).limit(total).to_batches(batch_rows):
            ids = batch.column("item_id").to_pylist()
            vectors = batch.column("vector")
            width = vectors.type.list_size
            matrix = vectors.flatten().to_numpy(zero_copy_only=False).astype(np.float64).reshape(len(ids), width)
            for item_id, row in zip(ids, matrix, strict=True):
                if item_id in sums:
                    sums[item_id] += row
                    counts[item_id] += 1
                else:
                    sums[item_id] = row.copy()
                    counts[item_id] = 1
        ids = sorted(sums)
        return ids, np.stack([sums[i] / counts[i] for i in ids]).astype(np.float32)

    def drop(self, name: str) -> None:
        with self._lock:
            self._tables.pop(name, None)
        if name in self.names():
            self._db.drop_table(name)
