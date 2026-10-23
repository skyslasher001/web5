"""The LanceDB vector store: search, per-item means for the Semantic layout, and future-proof queries."""

from pathlib import Path

import numpy as np
import pytest

from universe_vault.vectors import VectorRow, VectorStore


def _store(tmp_path: Path) -> VectorStore:
    store = VectorStore(tmp_path / "vectors")
    rows = [
        VectorRow(1, "a", "note", "2026-01-01", [1.0, 0.0, 0.0, 0.0]),
        VectorRow(2, "a", "note", "2026-01-01", [0.0, 1.0, 0.0, 0.0]),
        VectorRow(3, "b", "note", "2026-01-01", [0.0, 0.0, 1.0, 0.0]),
    ]
    store.add_many("text__m", rows)
    return store


def test_search_reads_distances_without_relying_on_auto_projection(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path)
    hits = store.search("text__m", [1.0, 0.0, 0.0, 0.0], limit=3)
    assert hits[0].item_id == "a" and hits[0].distance == pytest.approx(0.0)
    # LanceDB warns (on stderr, from Rust) when a query relies on `_distance` being added implicitly:
    # that behaviour is going away, and search would lose its distances.
    assert "_distance" not in capfd.readouterr().err


def test_item_means_average_each_items_chunks(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids, means = store.item_means("text__m", batch_rows=2)
    assert ids == ["a", "b"]
    np.testing.assert_allclose(means, [[0.5, 0.5, 0, 0], [0, 0, 1, 0]])
    assert store.item_mean("text__m", "a") == pytest.approx([0.5, 0.5, 0.0, 0.0])
    assert store.item_mean("text__m", "zzz") is None
    assert store.item_means("text__none")[0] == []
