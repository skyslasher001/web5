"""The Phase 4 benchmark data generator (scripts/seed_universe.py), at a small scale, read back through Core."""

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AUTH
from tests.integration.test_vault_api import BASE, Api
from tests.support.fake_ollama import EMBED_DIM, EMBED_MODEL, FakeOllama
from universe_core.app import create_app
from universe_core.settings import CoreSettings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_universe.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("seed_universe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_universe"] = module
    spec.loader.exec_module(module)
    return module


def test_seeded_universe_reads_back_with_galaxies_links_and_a_semantic_layout(
    make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama, tmp_path: Path
) -> None:
    seed = _load()
    settings = make_settings()
    result = seed.generate(settings.vault_dir, 400, embedder=f"{EMBED_MODEL}@bbb", dim=EMBED_DIM)  # type: ignore[attr-defined]
    assert result["items"] == 400 and result["links"] > 0

    with TestClient(create_app(settings), base_url=BASE) as client:
        api = Api(client, settings, fake_ollama.url)
        try:
            scene = api.get("/universe/items")
            assert scene["total"] == 400 and len(scene["ids"]) == 400
            assert len(set(scene["types"])) >= 8  # every kind of celestial object shows up
            assert sum(g is not None for g in scene["galaxies"]) > 300
            assert "inbox" in scene["statuses"]
            assert len(api.get("/projects")) == 12
            assert api.get("/universe/links")["ids"]
            # Seeded text is searchable, so search can fly the camera somewhere.
            assert api.get("/search", params={"q": "water", "limit": 20})["hits"]
            assert api.get("/layout/semantic")["status"] == "computing"
            api.drain()
            assert len(api.get("/layout/semantic")["ids"]) == 400
            # The files exist, so items open and notes read.
            first = scene["ids"][0]
            assert client.get(f"/api/v1/items/{first}/file", headers=AUTH).status_code == 200
            assert [v["n"] for v in api.get(f"/items/{first}")["versions"]] == [1]
        finally:
            api.close()

    with pytest.raises(SystemExit, match="already has items"):
        seed.generate(settings.vault_dir, 10)  # type: ignore[attr-defined]
