import socket
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.support.fake_ollama import FakeOllama
from universe_core.app import create_app
from universe_core.settings import CoreSettings

REPO = Path(__file__).resolve().parents[1]
TOKEN = "t" * 43
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def fake_ollama() -> Iterator[FakeOllama]:
    server = FakeOllama(delay_s=0.002).start()
    yield server
    server.stop()


@pytest.fixture
def make_settings(tmp_path: Path, fake_ollama: FakeOllama) -> Callable[..., CoreSettings]:
    def factory(**overrides: object) -> CoreSettings:
        values: dict[str, object] = {
            "session_token": TOKEN,
            "port": 47999,
            "allowed_origins": ("app://universe",),
            "data_dir": tmp_path / "data",
            "vault_dir": tmp_path / "vault",
            "agents_dir": REPO / "agents",
            "ollama_url": fake_ollama.url,
            "log_console": False,
        }
        values.update(overrides)
        return CoreSettings(**values)  # type: ignore[arg-type]

    return factory


@pytest.fixture
def client(make_settings: Callable[..., CoreSettings]) -> Iterator[TestClient]:
    settings = make_settings()
    with TestClient(create_app(settings), base_url=f"http://127.0.0.1:{settings.port}") as c:
        yield c
