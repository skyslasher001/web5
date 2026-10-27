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


def test_item_means_hold_little_more_than_the_result(tmp_path: Path) -> None:
    """The Semantic layout job reads 50k means. A per-row Python loop that copied every chunk as float64 took 9 s
    here and timed the layout out on CI's Windows runner (2026-10-27); it peaked at 12x the result's size."""
    import tracemalloc

    rng = np.random.default_rng(1)
    store = VectorStore(tmp_path / "vectors")
    vectors = rng.standard_normal((4000, 64)).astype(np.float32)
    # Two chunks per item, out of order, as LanceDB may return them.
    store.add_many("text__m", [VectorRow(n, f"i{(n * 7) % 2000:04d}", "note", "2026-01-01", list(map(float, v)))
                               for n, v in enumerate(vectors)])  # fmt: skip
    tracemalloc.start()
    try:
        ids, means = store.item_means("text__m", batch_rows=512)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert ids == sorted(ids) and len(ids) == 2000 and means.dtype == np.float32
    first = [n for n in range(4000) if (n * 7) % 2000 == 0]
    np.testing.assert_allclose(means[0], vectors[first].mean(axis=0), rtol=1e-5, atol=1e-6)
    assert peak < 4 * means.nbytes
