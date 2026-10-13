"""The Phase 1 "done when" backbone: real supervisor process (stdlib only) + real Core + fake Ollama.

Kill Core, watch it come back, and check the restart is on the event timeline.
"""

import json
import os
import secrets
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from tests.conftest import REPO, free_port
from tests.support.fake_ollama import FakeOllama

pytestmark = pytest.mark.slow
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def base_python() -> str:
    """The interpreter behind the venv, exactly as Electron main resolves it."""
    cfg = (REPO / ".venv" / "pyvenv.cfg").read_text().splitlines()
    home = next(line.split("=", 1)[1].strip() for line in cfg if line.startswith("home"))
    for name in ("python.exe", "python3", "python"):
        if (Path(home) / name).exists():
            return str(Path(home) / name)
    raise RuntimeError("base interpreter not found")


def venv_python() -> str:
    win = REPO / ".venv" / "Scripts" / "python.exe"
    return str(win if win.exists() else REPO / ".venv" / "bin" / "python")


def http(method: str, url: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, method=method, data=data)
    request.add_header("Authorization", f"Bearer {token}")
    if data:
        request.add_header("Content-Type", "application/json")
    with _opener.open(request, timeout=10) as response:
        return json.loads(response.read())


def wait(predicate, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError(f"timed out (last={last})")


def test_kill_core_and_watch_it_restart(tmp_path: Path) -> None:
    fake = FakeOllama(delay_s=0.001).start()
    control_token, session_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    core_port = free_port()
    env = {
        **os.environ,
        "UNIVERSE_SUPERVISOR_TOKEN": control_token,
        "UNIVERSE_SESSION_TOKEN": session_token,
        "UNIVERSE_DATA_DIR": str(tmp_path / "data"),
        "UNIVERSE_VAULT_DIR": str(tmp_path / "vault"),
        "UNIVERSE_REPO_ROOT": str(REPO),
        "UNIVERSE_SERVICE_PYTHON": venv_python(),
        "UNIVERSE_CORE_PORT": str(core_port),
        "UNIVERSE_OLLAMA_URL": fake.url,
        "UNIVERSE_MANAGE_OLLAMA": "0",
        "UNIVERSE_SUPERVISOR_WATCH_STDIN": "1",
    }
    proc = subprocess.Popen(
        [base_python(), "-I", "-S", str(REPO / "services" / "supervisor" / "run_supervisor.py")],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert proc.stdout is not None
        ready = json.loads(proc.stdout.readline())
        assert ready["event"] == "ready"
        control = f"http://127.0.0.1:{ready['control_port']}"
        core = f"http://127.0.0.1:{core_port}/api/v1"

        def core_state():
            status = http("GET", f"{control}/status", control_token)["services"]["core"]
            return status if status["state"] == "healthy" else None

        first = wait(core_state)
        sent = http("POST", f"{core}/chat", session_token, {"text": "hello"})
        wait(
            lambda: any(e["type"] == "agent.completed" for e in http("GET", f"{core}/events", session_token)["events"])
        )

        assert http("POST", f"{control}/services/core/kill", control_token)["ok"]
        # A *live* new Core: right after the kill the status can still say healthy with pid None.
        second = wait(lambda: (s := core_state()) and s["pid"] not in (None, first["pid"]) and s)
        assert second["restarts"] == 1

        events = http("GET", f"{core}/events?type=service.*", session_token)["events"]
        restarted = [e for e in events if e["type"] == "service.restarted"]
        assert restarted and restarted[0]["payload"]["reason"] == "crash"
        # data survived the crash
        msgs = http("GET", f"{core}/conversations/{sent['conversation_id']}/messages", session_token)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
    finally:
        assert proc.stdin is not None
        proc.stdin.close()  # parent gone → supervisor shuts everything down
        proc.wait(timeout=15)
        fake.stop()
    with pytest.raises(OSError):
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            f"http://127.0.0.1:{core_port}/api/v1/health", timeout=2
        )
