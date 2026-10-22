"""One supervised process: spawn, health-check, restart with backoff."""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from universe_supervisor.health import get_json
from universe_supervisor.winjob import JobObject

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

BACKOFF_MIN_S = 0.5
BACKOFF_MAX_S = 30.0
STABLE_RESET_S = 60.0
HEALTH_INTERVAL_S = 1.0
HEALTH_FAILURES_BEFORE_RESTART = 3


@dataclass
class ServiceSpec:
    name: str
    argv: list[str]
    health_url: str | None
    env: dict[str, str] = field(default_factory=dict)
    cwd: Path | None = None
    boot_timeout_s: float = 30.0
    background: bool = False  # lower OS priority


@dataclass
class ServiceRuntime:
    spec: ServiceSpec
    state: str = "stopped"  # stopped|starting|healthy|backoff|failed|external|missing|disabled
    proc: subprocess.Popen[bytes] | None = None
    started_at: float = 0.0
    healthy_since: float | None = None  # monotonic, for the state machine
    healthy_since_wall: float | None = None  # epoch seconds, for status()
    next_start_at: float = 0.0
    last_health_at: float = 0.0
    health_failures: int = 0
    crash_streak: int = 0
    restarts: int = 0
    crashes: int = 0  # crashes and failed boots only (not restarts you asked for)
    last_exit_code: int | None = None
    last_error: str | None = None
    start_reason: str = "boot"
    extra_env: dict[str, str] = field(default_factory=dict)

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "pid": self.proc.pid if self.proc and self.proc.poll() is None else None,
            "restarts": self.restarts,
            "healthy_since": self.healthy_since_wall,
            "last_exit_code": self.last_exit_code,
            "last_error": self.last_error,
            "health_url": self.spec.health_url,
        }


def out_log_path(log_dir: Path, name: str) -> Path:
    return log_dir / f"{name}.out.log"


def tail(path: Path, lines: int = 40, max_bytes: int = 64 * 1024) -> str:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(data.splitlines()[-lines:])


def spawn(spec: ServiceSpec, env: dict[str, str], log_dir: Path, job: JobObject) -> subprocess.Popen[bytes]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_log_path(log_dir, spec.name)
    if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
        log_path.replace(log_path.with_suffix(".log.1"))
    creationflags = 0
    if sys.platform == "win32":
        creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        if spec.background:
            creationflags |= BELOW_NORMAL_PRIORITY_CLASS
    # On POSIX a new session means a terminal Ctrl+C reaches the supervisor, not the children.
    with log_path.open("ab") as out:
        out.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} starting {spec.name}\n".encode())
        out.flush()
        proc = subprocess.Popen(
            spec.argv,
            env=env,
            cwd=str(spec.cwd) if spec.cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
        )
    if sys.platform == "win32":
        job.assign(int(proc._handle))  # type: ignore[attr-defined]
    return proc


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Hard-kill a service and everything it started.

    On Windows a venv's python.exe is a launcher that runs the real interpreter as its child, so
    killing only the launcher would orphan Core, still holding its port. On POSIX each service leads
    its own session (see spawn), so its process group is the tree.
    """
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
                timeout=10,
                check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass  # already gone, or taskkill unavailable: fall back to the direct kill below
    if proc.poll() is None:
        proc.kill()


def stop(proc: subprocess.Popen[bytes] | None, timeout: float = 5.0) -> int | None:
    if proc is None:
        return None
    if proc.poll() is None:
        if sys.platform == "win32":
            kill_tree(proc)  # Windows has no graceful signal for these services; terminate() is a hard kill too
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)  # the whole session, as a terminal's Ctrl+C would
            except OSError:
                proc.terminate()
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            proc.wait(5)
    return proc.returncode


def healthy(spec: ServiceSpec, proc: subprocess.Popen[bytes] | None) -> bool:
    if spec.health_url is None:
        return proc is not None and proc.poll() is None
    return get_json(spec.health_url) is not None


def backoff_delay(streak: int) -> float:
    return min(BACKOFF_MAX_S, BACKOFF_MIN_S * (2 ** max(0, streak - 1)))


Clock = Callable[[], float]
