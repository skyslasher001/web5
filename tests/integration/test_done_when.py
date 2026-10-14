"""Phase 2 "done when": drop in 500 mixed files and find any of them by keyword or meaning in under a second.

Runs the real ingest → pipeline → index path (an in-process worker) and Core's search API. Only the model
server is a stand-in (fake embeddings that put synonyms close together, tests/support/fake_ollama.py).
"""

import statistics
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.test_vault_api import Api, api  # noqa: F401 (the fixture)
from tests.support.seed import TOPICS, generate

COUNT = 500
KEYWORD_P95_MS = 100  # ARCHITECTURE.md §5.6 budgets, measured inside Core
HYBRID_P95_MS = 400
DONE_WHEN_MS = 1000  # wall time per query, request to response


def _marker(path: str) -> str:
    return Path(path).name.split("-")[0]


def _p95(values: list[float]) -> float:
    return sorted(values)[round(0.95 * (len(values) - 1))]


@pytest.fixture
def seeded(api: Api, tmp_path: Path) -> Iterator[dict[str, str]]:  # noqa: F811
    folder = tmp_path / "seed"
    seeded = generate(folder, COUNT)
    started = time.perf_counter()
    assert api.post("/ingest/paths", {"paths": [str(folder)]}, 202)["queued"] == 1
    api.drain()
    took = time.perf_counter() - started
    print(f"\ningested and processed {COUNT} files in {took:.1f} s ({COUNT / took:.1f} files/s)")
    yield {f.marker: f.topic for f in seeded}


@pytest.mark.slow
@pytest.mark.timeout(900)  # ingesting 500 files (OCR on ~80 images) takes minutes on a 4-core CI runner
def test_500_mixed_files_are_found_by_keyword_and_meaning_in_under_a_second(
    api: Api,  # noqa: F811
    seeded: dict[str, str],
) -> None:
    info = api.get("/system/vault")
    assert info["items"] == COUNT
    stats = api.get("/jobs/stats")
    assert stats["dead"] == 0, stats

    walls: list[float] = []
    hybrid: list[float] = []
    keyword: list[float] = []
    missed = []
    for marker in seeded:
        started = time.perf_counter()
        body = api.get("/search", params={"q": marker, "limit": 20})
        walls.append((time.perf_counter() - started) * 1000)
        hybrid.append(body["took_ms"])
        if not body["hits"] or _marker(body["hits"][0]["item"]["path"]) != marker:
            missed.append(marker)
        keyword.append(api.get("/search", params={"q": marker, "mode": "keyword", "limit": 20})["took_ms"])
    assert missed == [], f"{len(missed)} files not found first by their own name: {missed[:10]}"

    # Meaning: the query shares no word with the files, only meaning ("dog" → files about a puppy).
    for topic, _sentence, query in TOPICS:
        started = time.perf_counter()
        body = api.get("/search", params={"q": query, "limit": 20})
        walls.append((time.perf_counter() - started) * 1000)
        hybrid.append(body["took_ms"])
        top = [seeded.get(_marker(h["item"]["path"])) for h in body["hits"][:10]]
        # The stand-in hashes words into 1024 dimensions, so a random marker ("delta0211") can land on a
        # concept's dimension: allow one stray in the top 10, never at the top.
        assert body["semantic"] and top[0] == topic and top.count(topic) >= 9, f"{query!r} → {top}"

    print(
        f"wall ms: median {statistics.median(walls):.1f}, p95 {_p95(walls):.1f}, max {max(walls):.1f} · "
        f"in Core: hybrid p95 {_p95(hybrid):.1f}, keyword p95 {_p95(keyword):.1f}"
    )
    assert max(walls) < DONE_WHEN_MS
    assert _p95(hybrid) < HYBRID_P95_MS
    assert _p95(keyword) < KEYWORD_P95_MS
