"""The watchdog loop: keeps Core (and a managed Ollama) alive, tracks boot failures, safe mode and LKG."""

import json
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from universe_supervisor import __version__
from universe_supervisor.config import SupervisorConfig, find_ollama
from universe_supervisor.health import get_json
from universe_supervisor.jsonlog import JsonLog
from universe_supervisor.lkg import current_commit, lkg_pythonpath, prepare_worktree
from universe_supervisor.service import (
    HEALTH_FAILURES_BEFORE_RESTART,
    HEALTH_INTERVAL_S,
    STABLE_RESET_S,
    ServiceRuntime,
    ServiceSpec,
    backoff_delay,
    healthy,
    kill_tree,
    out_log_path,
    spawn,
    stop,
    tail,
)
from universe_supervisor.state import StateFile
from universe_supervisor.winjob import JobObject

BOOT_FAILURES_FOR_SAFE_MODE = 2
EXTERNAL_RECHECK_S = 5.0
TICK_S = 0.2

Emit = Callable[[dict[str, Any]], None]


class Supervisor:
    def __init__(
        self,
        config: SupervisorConfig,
        *,
        log: JsonLog,
        emit: Emit | None = None,
        core_argv: list[str] | None = None,
        ollama_exe: bool | str | None = True,
    ) -> None:
        self.config = config
        self.log = log
        self.emit = emit or (lambda _status: None)
        self.state = StateFile(config.state_path)
        self.job = JobObject()
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.started_at = time.time()
        self.running_from: str | None = None
        self._lkg_promoted = False
        self._last_status = ""
        self._next_external_check = 0.0

        core = ServiceSpec(
            name="core",
            argv=core_argv or [config.service_python, "-m", "universe_core"],
            health_url=f"http://127.0.0.1:{config.core_port}/api/v1/health",
            cwd=config.repo_root,
            boot_timeout_s=config.boot_timeout_s,
        )
        self.runtimes: dict[str, ServiceRuntime] = {"core": ServiceRuntime(core)}

        exe = find_ollama() if ollama_exe is True else (ollama_exe or None)
        ollama_port = config.ollama_url.rsplit(":", 1)[-1]
        ollama = ServiceSpec(
            name="ollama",
            argv=[exe or "ollama", "serve"],
            health_url=f"{config.ollama_url}/api/version",
            env={"OLLAMA_HOST": f"127.0.0.1:{ollama_port}"},
            boot_timeout_s=60.0,
        )
        self.ollama_exe = exe
        self.runtimes["ollama"] = ServiceRuntime(ollama, state="external")
        if self.state["safe_mode"]:
            self.log("safe_mode_resumed", reason=self.state["safe_mode_reason"])

    # ---------- environment ----------

    def _base_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in {"UNIVERSE_SUPERVISOR_TOKEN", "PYTHONPATH"}}
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _core_env(self, rt: ServiceRuntime) -> dict[str, str]:
        c = self.config
        env = self._base_env()
        env.update(
            UNIVERSE_SESSION_TOKEN=c.session_token,
            UNIVERSE_CORE_PORT=str(c.core_port),
            UNIVERSE_DATA_DIR=str(c.data_dir),
            UNIVERSE_VAULT_DIR=str(c.vault_dir),
            UNIVERSE_ALLOWED_ORIGINS=c.allowed_origins,
            UNIVERSE_OLLAMA_URL=c.ollama_url,
            UNIVERSE_LOG_QUIET="1",
            UNIVERSE_START_REASON=rt.start_reason,
            UNIVERSE_RESTART_COUNT=str(rt.restarts),
            UNIVERSE_LAST_EXIT="" if rt.last_exit_code is None else str(rt.last_exit_code),
        )
        if c.model_override:
            env["UNIVERSE_MODEL_FAST"] = c.model_override
        env.pop("UNIVERSE_SAFE_MODE", None)
        env.update(rt.extra_env)
        return env

    # ---------- main loop ----------

    def run(self) -> None:
        self.log("supervisor_started", version=__version__, pid=os.getpid(), core_port=self.config.core_port)
        while not self.stopped.is_set():
            with self.lock:
                self.tick()
                self._emit_if_changed()
            self.stopped.wait(TICK_S)

    def tick(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._tick_ollama_external(now)
        for rt in self.runtimes.values():
            self._tick_service(rt, now)
        self._maybe_promote_lkg(now)

    def _tick_ollama_external(self, now: float) -> None:
        rt = self.runtimes["ollama"]
        if rt.state not in ("external", "missing", "unreachable") or now < self._next_external_check:
            return
        self._next_external_check = now + EXTERNAL_RECHECK_S
        if get_json(rt.spec.health_url or "") is not None:
            rt.state = "external"
            rt.last_error = None
        elif self.config.manage_ollama and self.ollama_exe:
            rt.state = "stopped"  # not running: we start and supervise it
        elif not self.config.manage_ollama:
            rt.state = "unreachable"
            rt.last_error = f"Ollama is not answering at {self.config.ollama_url}"
        else:
            rt.state = "missing"
            rt.last_error = "Ollama is not installed (https://ollama.com/download)"

    def _start(self, rt: ServiceRuntime, now: float) -> None:
        env = self._core_env(rt) if rt.spec.name == "core" else {**self._base_env(), **rt.spec.env}
        try:
            rt.proc = spawn(rt.spec, env, self.config.log_dir, self.job)
        except OSError as exc:
            rt.proc = None
            rt.last_error = f"could not start: {exc}"
            self.log("service_spawn_failed", level="error", service=rt.spec.name, error=str(exc))
            self._on_boot_failure(rt, now, rt.last_error)
            return
        rt.state = "starting"
        rt.started_at = now
        rt.healthy_since = None
        rt.healthy_since_wall = None
        rt.health_failures = 0
        self.log("service_starting", service=rt.spec.name, pid=rt.proc.pid, reason=rt.start_reason)

    def _tick_service(self, rt: ServiceRuntime, now: float) -> None:
        if rt.state in ("stopped",) or (rt.state == "backoff" and now >= rt.next_start_at):
            self._start(rt, now)
            return
        if rt.state == "starting":
            assert rt.proc is not None
            code = rt.proc.poll()
            if code is not None:
                rt.last_exit_code = code
                self._on_boot_failure(rt, now, f"exited with code {code} before becoming healthy")
            elif healthy(rt.spec, rt.proc):
                rt.state = "healthy"
                rt.healthy_since = now
                rt.healthy_since_wall = time.time()
                rt.last_health_at = now
                rt.last_error = None
                self.log(
                    "service_healthy",
                    service=rt.spec.name,
                    pid=rt.proc.pid,
                    boot_s=round(now - rt.started_at, 2),
                )
                if rt.spec.name == "core" and self.state["core_boot_failures"]:
                    self.state.update(core_boot_failures=0)
            elif now - rt.started_at > rt.spec.boot_timeout_s:
                rt.last_exit_code = stop(rt.proc)
                self._on_boot_failure(rt, now, f"not healthy after {rt.spec.boot_timeout_s:.0f} s")
            return
        if rt.state == "healthy":
            assert rt.proc is not None
            code = rt.proc.poll()
            if code is not None:
                rt.last_exit_code = code
                self._on_crash(rt, now, f"exited with code {code}", "crash")
            elif now - rt.last_health_at >= HEALTH_INTERVAL_S:
                rt.last_health_at = now
                if healthy(rt.spec, rt.proc):
                    rt.health_failures = 0
                else:
                    rt.health_failures += 1
                    if rt.health_failures >= HEALTH_FAILURES_BEFORE_RESTART:
                        rt.last_exit_code = stop(rt.proc)
                        self._on_crash(rt, now, "stopped answering health checks", "health")

    def _schedule_restart(self, rt: ServiceRuntime, now: float, reason: str) -> None:
        rt.crash_streak += 1
        delay = backoff_delay(rt.crash_streak)
        rt.state = "backoff"
        rt.next_start_at = now + delay
        rt.restarts += 1
        rt.start_reason = reason
        self.log("service_restart_scheduled", service=rt.spec.name, delay_s=delay, reason=reason)

    def _adopt_external_ollama(self, rt: ServiceRuntime) -> bool:
        """Our `ollama serve` died, but an Ollama answers anyway (say the tray app won the port): use it."""
        if rt.spec.name != "ollama" or get_json(rt.spec.health_url or "") is None:
            return False
        rt.proc = None
        rt.state = "external"
        rt.crash_streak = 0
        rt.last_error = None
        self._next_external_check = 0.0
        self.log("ollama_external_adopted", url=self.config.ollama_url)
        return True

    def _on_crash(self, rt: ServiceRuntime, now: float, why: str, reason: str) -> None:
        if self._adopt_external_ollama(rt):
            return
        if rt.healthy_since is not None and now - rt.healthy_since > STABLE_RESET_S:
            rt.crash_streak = 0
        rt.last_error = self._error_with_tail(rt, why)
        self.log("service_crashed", level="error", service=rt.spec.name, why=why)
        self._schedule_restart(rt, now, reason)

    def _on_boot_failure(self, rt: ServiceRuntime, now: float, why: str) -> None:
        if self._adopt_external_ollama(rt):
            return
        rt.last_error = self._error_with_tail(rt, why)
        self.log("service_boot_failed", level="error", service=rt.spec.name, why=why)
        if rt.spec.name != "core":
            self._schedule_restart(rt, now, "boot-retry")
            return
        failures = int(self.state["core_boot_failures"]) + 1
        self.state.update(core_boot_failures=failures)
        if failures < BOOT_FAILURES_FOR_SAFE_MODE:
            self._schedule_restart(rt, now, "boot-retry")
        elif not self.state["safe_mode"]:
            self._enter_safe_mode(rt, now, f"Core failed to start {failures} times in a row: {why}")
        else:
            rt.state = "failed"
            self.log("core_failed_in_safe_mode", level="critical", why=why)

    def _error_with_tail(self, rt: ServiceRuntime, why: str) -> str:
        lines = tail(out_log_path(self.config.log_dir, rt.spec.name), lines=8)
        return f"{why}\n{lines}".strip()

    # ---------- safe mode and LKG ----------

    def _enter_safe_mode(self, rt: ServiceRuntime, now: float, reason: str) -> None:
        self.state.update(safe_mode=True, safe_mode_reason=reason, core_boot_failures=0)
        self.log("safe_mode_entered", level="critical", reason=reason)
        self._configure_safe_mode(rt)
        rt.crash_streak = 0
        rt.start_reason = "safe-mode"
        rt.state = "stopped"

    def _configure_safe_mode(self, rt: ServiceRuntime) -> None:
        rt.extra_env = {"UNIVERSE_SAFE_MODE": "1"}
        self.running_from = "current"
        lkg = self.state["lkg"]
        if lkg and lkg.get("commit"):
            if prepare_worktree(self.config.repo_root, self.config.lkg_dir, lkg["commit"]):
                rt.extra_env["PYTHONPATH"] = os.pathsep.join(lkg_pythonpath(self.config.lkg_dir))
                rt.extra_env["UNIVERSE_AGENTS_DIR"] = str(self.config.lkg_dir / "agents")
                self.running_from = "lkg"
            else:
                self.log("lkg_worktree_failed", level="error", commit=lkg["commit"])

    def _maybe_promote_lkg(self, now: float) -> None:
        rt = self.runtimes["core"]
        if self._lkg_promoted or self.state["safe_mode"] or rt.state != "healthy" or rt.healthy_since is None:
            return
        if now - rt.healthy_since < self.config.lkg_stable_s:
            return
        self._lkg_promoted = True
        commit = current_commit(self.config.repo_root)
        if commit is None:
            self.log("lkg_skipped", reason="not a git checkout")
            return
        self.state.update(lkg={"commit": commit, "promoted_at": time.time()})
        self.log("lkg_promoted", commit=commit)

    # ---------- control actions (called from the control API thread) ----------

    def prepare_initial(self) -> None:
        """Called once before run(): resume safe mode if the previous session ended in it."""
        with self.lock:
            if self.state["safe_mode"]:
                self._configure_safe_mode(self.runtimes["core"])
                self.runtimes["core"].start_reason = "safe-mode"

    def restart(self, name: str) -> bool:
        with self.lock:
            rt = self.runtimes.get(name)
            if rt is None or rt.state in ("external", "missing", "unreachable"):
                return False
            rt.last_exit_code = stop(rt.proc)
            rt.proc = None
            rt.restarts += 1
            rt.crash_streak = 0
            rt.start_reason = "manual"
            rt.state = "stopped"
            self.log("service_restart_requested", service=name)
            return True

    def kill(self, name: str) -> bool:
        """Hard-kill without telling the watchdog, as a crash would (used to demo and test recovery)."""
        with self.lock:
            rt = self.runtimes.get(name)
            if rt is None or rt.proc is None or rt.proc.poll() is not None:
                return False
            kill_tree(rt.proc)
            self.log("service_killed_on_request", service=name, pid=rt.proc.pid)
            return True

    def exit_safe_mode(self) -> bool:
        with self.lock:
            if not self.state["safe_mode"]:
                return False
            self.state.update(safe_mode=False, safe_mode_reason=None, core_boot_failures=0)
            rt = self.runtimes["core"]
            rt.extra_env = {}
            self.running_from = None
            stop(rt.proc)
            rt.proc = None
            rt.crash_streak = 0
            rt.start_reason = "manual"
            rt.state = "stopped"
            self.log("safe_mode_exited")
            return True

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "supervisor": {"version": __version__, "pid": os.getpid(), "started_at": self.started_at},
                "core_url": f"http://127.0.0.1:{self.config.core_port}",
                "safe_mode": {
                    "active": bool(self.state["safe_mode"]),
                    "reason": self.state["safe_mode_reason"],
                    "running_from": self.running_from if self.state["safe_mode"] else None,
                    "lkg_commit": (self.state["lkg"] or {}).get("commit"),
                },
                "services": {name: rt.status() for name, rt in self.runtimes.items()},
            }

    def logs(self, name: str, lines: int = 200) -> str | None:
        if name not in self.runtimes and name != "supervisor":
            return None
        if name == "supervisor":
            return tail(self.config.log_dir / "supervisor.jsonl", lines)
        return tail(out_log_path(self.config.log_dir, name), lines)

    def _emit_if_changed(self) -> None:
        status = self.status()
        encoded = json.dumps(status, sort_keys=True, default=str)
        if encoded != self._last_status:
            self._last_status = encoded
            self.emit(status)

    def shutdown(self) -> None:
        self.stopped.set()
        with self.lock:
            for name in ("core", "ollama"):
                rt = self.runtimes[name]
                if rt.proc is not None:
                    stop(rt.proc)
                    rt.proc = None
                if rt.state not in ("external", "missing", "unreachable"):
                    rt.state = "stopped"
        self.log("supervisor_stopped")
