"""Core must exit when its parent dies (supervisor SIGKILLed, or the Windows venv launcher killed)."""

import contextlib
import os
import secrets
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import psutil
import pytest

from tests.conftest import REPO, free_port

pytestmark = pytest.mark.slow
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _healthy(port: int) -> bool:
    try:
        with _opener.open(f"http://127.0.0.1:{port}/api/v1/health", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def test_core_exits_and_frees_its_port_when_the_parent_dies(tmp_path: Path) -> None:
    port = free_port()
    env = {
        **os.environ,
        "UNIVERSE_SESSION_TOKEN": secrets.token_urlsafe(32),
        "UNIVERSE_CORE_PORT": str(port),
        "UNIVERSE_DATA_DIR": str(tmp_path / "data"),
        "UNIVERSE_VAULT_DIR": str(tmp_path / "vault"),
        "UNIVERSE_AGENTS_DIR": str(REPO / "agents"),
        "UNIVERSE_OLLAMA_URL": "http://127.0.0.1:9",
        "UNIVERSE_LOG_QUIET": "1",
    }
    # A stand-in parent that starts Core, prints its pid, then waits to be killed.
    parent_code = textwrap.dedent(
        f"""
        import subprocess, sys, time
        child = subprocess.Popen([{sys.executable!r}, "-m", "universe_core"])
        print(child.pid, flush=True)
        time.sleep(600)
        """
    )
    parent = subprocess.Popen([sys.executable, "-c", parent_code], env=env, stdout=subprocess.PIPE, text=True)
    assert parent.stdout is not None
    core_pid = int(parent.stdout.readline())
    try:
        deadline = time.monotonic() + 30
        while not _healthy(port):
            assert time.monotonic() < deadline, "Core did not start"
            time.sleep(0.1)
        parent.kill()  # the supervisor (or launcher) disappears without cleaning up
        parent.wait(10)
        deadline = time.monotonic() + 10
        while _healthy(port):
            assert time.monotonic() < deadline, "orphaned Core kept serving"
            time.sleep(0.1)
        try:
            psutil.Process(core_pid).wait(timeout=10)  # it exits by itself; not our child, so this polls
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            pytest.fail("orphaned Core released its port but did not exit")
    finally:
        if psutil.pid_exists(core_pid):
            with contextlib.suppress(psutil.Error):
                psutil.Process(core_pid).kill()
