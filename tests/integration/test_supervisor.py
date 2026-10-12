"""Supervisor state machine with a fake Core process (fast, deterministic)."""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.conftest import REPO, free_port
from universe_supervisor.config import SupervisorConfig
from universe_supervisor.control import ControlServer
from universe_supervisor.jsonlog import JsonLog
from universe_supervisor.supervisor import Supervisor

pytestmark = pytest.mark.slow

FAKE_CORE = REPO / "tests" / "support" / "fake_core.py"
CONTROL_TOKEN = "c" * 40


class Harness:
    def __init__(self, tmp: Path, repo: Path, *, lkg_stable_s: float = 3600) -> None:
        self.tmp = tmp
        self.control_file = tmp / "mode"
        self.env_out = tmp / "env.jsonl"
        self.set_mode("ok")
        self.port = free_port()
        self.config = SupervisorConfig(
            control_token=CONTROL_TOKEN,
            session_token="s" * 40,
            repo_root=repo,
            data_dir=tmp / "data",
            vault_dir=tmp / "vault",
            service_python=sys.executable,
            core_port=self.port,
            manage_ollama=False,
            ollama_url=f"http://127.0.0.1:{free_port()}",
            lkg_stable_s=lkg_stable_s,
            boot_timeout_s=5,
        )
        self.statuses: list[dict] = []
        self.sup = Supervisor(
            self.config,
            log=JsonLog(self.config.log_dir / "supervisor.jsonl", echo=False),
            emit=self.statuses.append,
            core_argv=[sys.executable, str(FAKE_CORE)],
            ollama_exe=None,
        )

    def set_mode(self, mode: str) -> None:
        self.control_file.write_text(mode)

    def starts(self) -> list[dict]:
        if not self.env_out.exists():
            return []
        return [json.loads(line) for line in self.env_out.read_text().splitlines()]

    def run_until(self, predicate, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.sup.lock:
                self.sup.tick()
                self.sup._emit_if_changed()
            if predicate(self.sup.status()):
                return
            time.sleep(0.05)
        raise AssertionError(f"timed out; status={json.dumps(self.sup.status(), indent=1)}")


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    h = Harness(tmp_path, REPO)
    monkeypatch.setenv("FAKE_CORE_CONTROL", str(h.control_file))
    monkeypatch.setenv("FAKE_CORE_ENV_OUT", str(h.env_out))
    monkeypatch.setenv("UNIVERSE_SUPERVISOR_TOKEN", CONTROL_TOKEN)
    yield h
    h.sup.shutdown()


def core(status: dict) -> dict:
    return status["services"]["core"]


def test_starts_core_and_keeps_secrets_scoped(harness: Harness) -> None:
    harness.run_until(lambda s: core(s)["state"] == "healthy")
    first = harness.starts()[0]
    assert first["UNIVERSE_SESSION_TOKEN"] == "s" * 40
    assert first["UNIVERSE_SUPERVISOR_TOKEN"] is None  # the control token never reaches services
    assert first["UNIVERSE_START_REASON"] == "boot"


def test_crash_is_restarted_with_reason(harness: Harness) -> None:
    harness.run_until(lambda s: core(s)["state"] == "healthy")
    assert harness.sup.kill("core")
    harness.run_until(lambda s: core(s)["state"] == "healthy" and core(s)["restarts"] == 1)
    restarted = harness.starts()[-1]
    assert restarted["UNIVERSE_START_REASON"] == "crash"
    assert restarted["UNIVERSE_RESTART_COUNT"] == "1"
    assert restarted["UNIVERSE_LAST_EXIT"] not in (None, "", "0")


def test_unhealthy_core_is_replaced(harness: Harness) -> None:
    harness.run_until(lambda s: core(s)["state"] == "healthy")
    harness.set_mode("unhealthy")
    proc = harness.sup.runtimes["core"].proc
    assert proc is not None
    proc.kill()  # next start reads the new mode
    harness.run_until(lambda s: core(s)["restarts"] >= 1 and core(s)["state"] in ("starting", "backoff"))
    harness.set_mode("ok")
    harness.run_until(lambda s: core(s)["state"] == "healthy", timeout=20)


def test_two_failed_boots_enter_safe_mode_and_it_persists(harness: Harness, tmp_path: Path) -> None:
    harness.set_mode("crash")
    harness.run_until(lambda s: s["safe_mode"]["active"])
    status = harness.sup.status()
    assert "failed to start 2 times" in status["safe_mode"]["reason"]
    assert "simulated startup crash" in core(status)["last_error"]
    harness.set_mode("ok")
    harness.run_until(lambda s: core(s)["state"] == "healthy")
    safe_start = harness.starts()[-1]
    assert safe_start["UNIVERSE_SAFE_MODE"] == "1" and safe_start["UNIVERSE_START_REASON"] == "safe-mode"
    # a new supervisor (app relaunch) resumes safe mode from state.json
    state = json.loads(harness.config.state_path.read_text())
    assert state["safe_mode"] is True
    assert harness.sup.exit_safe_mode()
    harness.run_until(lambda s: not s["safe_mode"]["active"] and core(s)["state"] == "healthy")
    assert harness.starts()[-1]["UNIVERSE_SAFE_MODE"] is None


def test_safe_mode_gives_up_after_two_more_failures(harness: Harness) -> None:
    harness.set_mode("crash")
    harness.run_until(lambda s: core(s)["state"] == "failed", timeout=20)
    assert harness.sup.status()["safe_mode"]["active"]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_lkg_is_promoted_and_used_by_safe_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    (repo / "services" / "core" / "src").mkdir(parents=True)
    (repo / "agents").mkdir()
    (repo / "agents" / "core.yaml").write_text("id: core\n")
    _git(tmp_path, "init", "-q", str(repo))
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "good")
    commit = _git(repo, "rev-parse", "HEAD")

    h = Harness(tmp_path, repo, lkg_stable_s=0.3)
    monkeypatch.setenv("FAKE_CORE_CONTROL", str(h.control_file))
    monkeypatch.setenv("FAKE_CORE_ENV_OUT", str(h.env_out))
    try:
        h.run_until(lambda s: s["safe_mode"]["lkg_commit"] == commit)
        h.set_mode("crash")
        h.sup.kill("core")
        h.run_until(lambda s: s["safe_mode"]["active"])
        h.set_mode("ok")
        h.run_until(lambda s: core(s)["state"] == "healthy")
        assert h.sup.status()["safe_mode"]["running_from"] == "lkg"
        safe_start = h.starts()[-1]
        lkg_dir = repo / ".universe-runtime" / "lkg"
        assert str(lkg_dir / "services" / "core" / "src") in safe_start["PYTHONPATH"]
        assert safe_start["UNIVERSE_AGENTS_DIR"] == str(lkg_dir / "agents")
        assert _git(lkg_dir, "rev-parse", "HEAD") == commit
    finally:
        h.sup.shutdown()


def _call(port: int, method: str, path: str, token: str | None = CONTROL_TOKEN, host: str | None = None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if host:
        request.add_header("Host", host)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_control_api_requires_token_and_loopback_host(harness: Harness) -> None:
    server = ControlServer(harness.sup, CONTROL_TOKEN, on_shutdown=lambda: None)
    server.start()
    try:
        assert _call(server.port, "GET", "/status", token=None)[0] == 401
        assert _call(server.port, "GET", "/status", token="wrong" * 10)[0] == 401
        assert _call(server.port, "GET", "/status", host="evil.example")[0] == 403
        code, body = _call(server.port, "GET", "/status")
        assert code == 200 and "core" in body["services"]
        assert _call(server.port, "POST", "/services/nope/restart")[0] == 409
        assert _call(server.port, "GET", "/logs/supervisor")[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_shutdown_stops_children(harness: Harness) -> None:
    harness.run_until(lambda s: core(s)["state"] == "healthy")
    proc = harness.sup.runtimes["core"].proc
    harness.sup.shutdown()
    assert proc is not None and proc.poll() is not None
