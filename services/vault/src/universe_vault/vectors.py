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
            for r in query.select(["item_id", "chunk_id"]).to_list()
        ]

    def drop(self, name: str) -> None:
        with self._lock:
            self._tables.pop(name, None)
        if name in self.names():
            self._db.drop_table(name)
