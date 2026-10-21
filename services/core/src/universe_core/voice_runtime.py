"""The voice process, run by Core like the pipeline workers (ADR-0016; ADR-0010 set the precedent).

Started when you turn voice on and stopped when you turn it off or the kill switch engages, so no voice models sit
in memory otherwise. Core and the process share a per-boot key; the renderer gets a single-use ticket from Core
and opens the WebSocket straight to the process on loopback (audio never passes through Core's event loop).

What the process can hear is decided elsewhere: the microphone permission belongs to Electron main (protected,
docs/proposals/phase-7-consent.md). Without it Chromium never hands the renderer a mic stream, and voice can still
speak answers.
"""

import asyncio
import contextlib
import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

from universe_common.egress import EgressGate
from universe_common.log import get_logger, register_secret
from universe_voice import models, tickets

log = get_logger(__name__)

CREATE_NO_WINDOW = 0x08000000
State = Literal["off", "starting", "ready", "failed"]
Publish = Callable[[str, dict[str, Any]], None]


# Agent YAMLs name a voice by character; these are the Kokoro voices that play them (any Kokoro id works too).
VOICE_STYLES = {
    "calm-neutral": "af_heart",
    "bright-guide": "af_nova",
    "warm-archivist": "bf_emma",
    "clear-scribe": "am_michael",
    "dry-skeptic": "bm_george",
    "curious-reporter": "am_puck",
    "steady-engineer": "am_onyx",
    "watchful-guard": "bm_lewis",
}
# Forge and Sentinel's YAMLs are protected and have no voice field: they get theirs here.
AGENT_FALLBACK = {"forge": "steady-engineer", "sentinel": "watchful-guard"}
DEFAULT_VOICE = "af_heart"


@dataclass
class VoiceConfig:
    stt: str | None = None  # a catalog id, or the best installed
    wake_phrase: str = "hey universe"
    voice: str = DEFAULT_VOICE  # for anything without a voice of its own
    mode: Literal["push_to_talk", "wake", "continuous"] = "push_to_talk"
    speed: float = 1.0
    agents: dict[str, str] = field(default_factory=dict)  # your per-agent picks (Kokoro ids)


def agent_voice(config: VoiceConfig, agent_id: str, yaml_voice: str | None) -> str:
    """Your pick for this agent, else its YAML voice (a style or a Kokoro id), else the default."""
    if agent_id in config.agents:
        return config.agents[agent_id]
    named = yaml_voice or AGENT_FALLBACK.get(agent_id)
    if named is None:
        return config.voice
    return VOICE_STYLES.get(named, named)


class VoiceManager:
    READY_TIMEOUT_S = 90.0  # first start loads Whisper + Kokoro (a few seconds; slow disks more)
    BACKOFF_MIN_S = 1.0
    BACKOFF_MAX_S = 30.0
    STABLE_S = 60.0
    MAX_FAST_FAILURES = 5

    def __init__(
        self,
        *,
        models_dir: Path,
        log_dir: Path,
        gate: EgressGate,
        publish: Publish,
        env: dict[str, str] | None = None,
        command: list[str] | None = None,
    ) -> None:
        self.models_dir = models_dir
        self._log_dir = log_dir
        self._publish = publish
        self.env = env if env is not None else dict(os.environ)
        self.command = command or [sys.executable, "-m", "universe_voice"]
        self._client = gate.async_client(purpose="voice", local_only=True, timeout=2.0)
        self._key = secrets.token_bytes(32)
        register_secret(self._key.hex())
        self.state: State = "off"
        self.reason: str | None = None
        self.port: int | None = None
        self.health: dict[str, Any] = {}
        self._proc: subprocess.Popen[bytes] | None = None
        self._wanted = False
        self._config = VoiceConfig()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._failures = 0
        self._started_at = 0.0

    # ---------- lifecycle ----------

    async def start(self, config: VoiceConfig) -> None:
        async with self._lock:
            self._wanted, self._config, self._failures = True, config, 0
            if self._proc is not None and self._proc.poll() is None and self.state == "ready":
                return
            await self._spawn_and_wait()
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._monitor(), name="voice-monitor")

    async def restart(self, config: VoiceConfig) -> None:
        """New settings (another Whisper, wake phrase, default voice): the process reads them at start."""
        await self.stop(reason=None)
        await self.start(config)

    async def stop(self, *, reason: str | None = None) -> None:
        self._wanted = False
        task, self._task = self._task, None
        if task is not None:  # first, so a restart in progress can't hold the lock
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        async with self._lock:
            # A start() queued on the lock may have run first and made a new monitor: this stop still wins.
            self._wanted = False
            late, self._task = self._task, None
            if late is not None:
                late.cancel()
            await self._terminate()
            self._set("off", reason)

    async def aclose(self) -> None:
        await self.stop()
        await self._client.aclose()

    def ticket(self) -> str:
        if self.state != "ready" or self.port is None:
            raise RuntimeError("voice is not running")
        return tickets.mint(self._key)

    @property
    def url(self) -> str | None:
        return f"ws://127.0.0.1:{self.port}/ws" if self.state == "ready" and self.port else None

    def status(self) -> dict[str, Any]:
        proc = self._proc
        return {
            "state": self.state,
            "reason": self.reason,
            "pid": proc.pid if proc is not None and proc.poll() is None else None,
            "stt": self.health.get("stt"),
            "tts": self.health.get("tts"),
            "voices": self.health.get("voices", []),
        }

    # ---------- internals ----------

    def _set(self, state: State, reason: str | None) -> None:
        changed = (state, reason) != (self.state, self.reason)
        self.state, self.reason = state, reason
        if changed:
            self._publish("voice.service.changed", {"state": state, "reason": reason})

    async def _spawn_and_wait(self) -> None:
        await self._terminate()  # a half-started process from a cancelled monitor must not be orphaned
        self._set("starting", None)
        self.port = None
        port_file = self._log_dir / "voice.port"  # the process binds any free loopback port and writes it here
        port_file.unlink(missing_ok=True)
        env = {
            **self.env,
            "UNIVERSE_VOICE_KEY": self._key.hex(),
            "UNIVERSE_VOICE_PORT": "0",
            "UNIVERSE_VOICE_PORT_FILE": str(port_file),
            "UNIVERSE_VOICE_MODELS": str(self.models_dir),
            "UNIVERSE_VOICE_WAKE": self._config.wake_phrase,
            "UNIVERSE_VOICE_VOICE": self._config.voice,
            "PYTHONUNBUFFERED": "1",
        }
        if self._config.stt:
            env["UNIVERSE_VOICE_STT"] = self._config.stt
        else:
            env.pop("UNIVERSE_VOICE_STT", None)
        await asyncio.to_thread(self._popen, env)  # sets self._proc itself, so a cancellation can't lose it
        assert self._proc is not None
        self._started_at = time.monotonic()
        log.info("voice_spawned", pid=self._proc.pid)
        deadline = time.monotonic() + self.READY_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                self._set("failed", f"the voice process exited ({self._proc.returncode}): {self._last_log_line()}")
                return
            if self.port is None:
                with contextlib.suppress(OSError, ValueError):
                    self.port = int(port_file.read_text(encoding="utf-8"))
                if self.port is None:
                    await asyncio.sleep(0.1)
                    continue
            with contextlib.suppress(httpx.HTTPError, ValueError):
                response = await self._client.get(f"http://127.0.0.1:{self.port}/health")
                if response.status_code == 200:
                    self.health = response.json()
                    self._set("ready", None)
                    return
            await asyncio.sleep(0.25)
        await self._terminate()
        self._set("failed", f"the voice process didn't come up within {self.READY_TIMEOUT_S:.0f} s")

    def _popen(self, env: dict[str, str]) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        with (self._log_dir / "voice.out.log").open("ab") as out:
            self._proc = subprocess.Popen(
                self.command,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

    def _last_log_line(self) -> str:
        path = self._log_dir / "voice.out.log"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        except OSError:
            return "no log"
        return lines[-1][:300] if lines else "no output"

    async def _terminate(self) -> None:
        proc, self._proc = self._proc, None
        self.health = {}
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, 5)
        except subprocess.TimeoutExpired:
            proc.kill()
            await asyncio.to_thread(proc.wait, 5)

    async def _monitor(self) -> None:
        """Restart a crashed voice process with backoff; give up after repeated fast failures."""
        while self._wanted:
            await asyncio.sleep(1.0)
            proc = self._proc
            if proc is not None and proc.poll() is None and self.state == "ready":
                continue
            fast = time.monotonic() - self._started_at < self.STABLE_S
            self._failures = self._failures + 1 if fast else 1
            if self._failures > self.MAX_FAST_FAILURES:
                async with self._lock:
                    await self._terminate()
                    self._set("failed", f"the voice process keeps failing: {self.reason or self._last_log_line()}")
                    self._wanted = False
                return
            delay = min(self.BACKOFF_MAX_S, self.BACKOFF_MIN_S * 2 ** (self._failures - 1))
            log.error("voice_exited", restart_in_s=delay, reason=self.reason)
            await asyncio.sleep(delay)
            async with self._lock:
                if not self._wanted:
                    return
                await self._terminate()
                await self._spawn_and_wait()


def load_config(raw: str | None) -> VoiceConfig:
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    known = {k: v for k, v in data.items() if k in VoiceConfig.__dataclass_fields__} if isinstance(data, dict) else {}
    return VoiceConfig(**known)


def dump_config(config: VoiceConfig) -> str:
    return json.dumps(asdict(config), sort_keys=True)


# ---------- installing models ----------


@dataclass
class InstallState:
    state: Literal["downloading", "installing", "done", "failed"]
    done: int = 0
    total: int = 0
    error: str | None = None


class ModelInstaller:
    """Downloads a catalog model through the egress gate (offline mode and the kill switch block it, the audit log
    records every request, redirects included), then `models.place` verifies the pinned SHA-256 and installs it."""

    CHUNK = 1 << 20

    def __init__(
        self,
        *,
        models_dir: Path,
        gate: EgressGate,
        publish: Publish,
        on_installed: Callable[[models.VoiceModel], Any] | None = None,
    ) -> None:
        self.models_dir = models_dir
        self._gate = gate
        self._publish = publish
        self._on_installed = on_installed
        self.installs: dict[str, InstallState] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, model: models.VoiceModel) -> InstallState:
        task = self._tasks.get(model.id)
        if task is not None and not task.done():
            return self.installs[model.id]
        self.installs[model.id] = InstallState("downloading", total=model.size)
        self._tasks[model.id] = asyncio.create_task(self._install(model), name=f"voice-install-{model.id}")
        return self.installs[model.id]

    async def wait(self, model_id: str) -> None:
        task = self._tasks.get(model_id)
        if task is not None:
            await asyncio.shield(task)

    async def aclose(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        for task in self._tasks.values():
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _install(self, model: models.VoiceModel) -> None:
        state = self.installs[model.id]
        staging = self.models_dir / ".downloads"
        staging.mkdir(parents=True, exist_ok=True)
        timeout = httpx.Timeout(30.0, read=120.0)
        last_pct = -1
        try:
            async with self._gate.async_client(purpose="voice-model", actor="user", timeout=timeout) as client:
                for download in model.downloads:
                    part = staging / f"{model.id}-{secrets.token_hex(4)}-{Path(download.url).name}.part"
                    try:
                        async with client.stream("GET", download.url, follow_redirects=True) as response:
                            response.raise_for_status()
                            with part.open("wb") as out:
                                async for block in response.aiter_bytes(self.CHUNK):
                                    out.write(block)
                                    state.done += len(block)
                                    if state.done > model.size:
                                        raise models.InstallError(f"{model.id}: larger than its pinned size")
                                    pct = state.done * 100 // max(1, state.total)
                                    if pct != last_pct:
                                        last_pct = pct
                                        self._publish(
                                            "voice.model.progress",
                                            {"id": model.id, "done": state.done, "total": state.total},
                                        )
                        state.state = "installing"
                        await asyncio.to_thread(models.place, self.models_dir, model, download, part)
                        state.state = "downloading"
                    finally:
                        part.unlink(missing_ok=True)
            if not models.installed(self.models_dir, model):
                raise models.InstallError(f"{model.id}: files missing after install")
        except asyncio.CancelledError:
            state.state, state.error = "failed", "cancelled"
            raise
        except (httpx.HTTPError, OSError, models.InstallError) as exc:
            state.state, state.error = "failed", f"{type(exc).__name__}: {exc}"[:500]
            log.warning("voice_model_install_failed", model=model.id, error=state.error)
            self._publish("voice.model.failed", {"id": model.id, "error": state.error})
            return
        state.state = "done"
        self._publish("voice.model.installed", {"id": model.id, "kind": model.kind})
        if self._on_installed is not None:
            result = self._on_installed(model)
            if asyncio.iscoroutine(result):
                await result


class VoiceService:
    """What Core holds for voice: the process, the installer, and your settings (the `voice.config` setting)."""

    SETTINGS_KEY = "voice.config"

    def __init__(
        self,
        *,
        manager: VoiceManager,
        installer: ModelInstaller,
        read_setting: Callable[[str], str | None],
    ) -> None:
        self.manager, self.installer = manager, installer
        self.models_dir = installer.models_dir
        self._read = read_setting

    def config(self) -> VoiceConfig:
        return load_config(self._read(self.SETTINGS_KEY))

    async def aclose(self) -> None:
        await self.installer.aclose()
        await self.manager.aclose()
