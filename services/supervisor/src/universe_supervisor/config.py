"""Supervisor configuration from environment variables (set by Electron main)."""

import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SupervisorConfig:
    control_token: str
    session_token: str
    repo_root: Path
    data_dir: Path
    vault_dir: Path
    service_python: str
    core_port: int = 47821
    allowed_origins: str = "app://universe"
    ollama_url: str = "http://127.0.0.1:11434"
    manage_ollama: bool = True
    model_override: str = ""
    watch_stdin: bool = False
    lkg_stable_s: float = 60.0
    boot_timeout_s: float = 30.0

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "supervisor" / "state.json"

    @property
    def lkg_dir(self) -> Path:
        return self.repo_root / ".universe-runtime" / "lkg"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SupervisorConfig":
        env = os.environ if env is None else env
        control = env.get("UNIVERSE_SUPERVISOR_TOKEN", "")
        session = env.get("UNIVERSE_SESSION_TOKEN", "")
        if len(control) < 32 or len(session) < 32:
            raise ConfigError("UNIVERSE_SUPERVISOR_TOKEN and UNIVERSE_SESSION_TOKEN must be set (32+ chars)")
        repo = Path(env.get("UNIVERSE_REPO_ROOT") or Path(__file__).resolve().parents[4])
        data_dir = env.get("UNIVERSE_DATA_DIR")
        vault_dir = env.get("UNIVERSE_VAULT_DIR")
        if not data_dir or not vault_dir:
            raise ConfigError("UNIVERSE_DATA_DIR and UNIVERSE_VAULT_DIR must be set")
        default_python = repo / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        try:
            port = int(env.get("UNIVERSE_CORE_PORT") or 47821)
            lkg_stable = float(env.get("UNIVERSE_LKG_STABLE_S") or 60)
            boot_timeout = float(env.get("UNIVERSE_BOOT_TIMEOUT_S") or 30)
        except ValueError as exc:
            raise ConfigError(f"bad numeric setting: {exc}") from exc
        return cls(
            control_token=control,
            session_token=session,
            repo_root=repo,
            data_dir=Path(data_dir),
            vault_dir=Path(vault_dir),
            service_python=env.get("UNIVERSE_SERVICE_PYTHON") or str(default_python),
            core_port=port,
            allowed_origins=env.get("UNIVERSE_ALLOWED_ORIGINS") or "app://universe",
            ollama_url=(env.get("UNIVERSE_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/"),
            manage_ollama=_flag(env.get("UNIVERSE_MANAGE_OLLAMA"), True),
            model_override=env.get("UNIVERSE_MODEL_FAST") or "",
            watch_stdin=_flag(env.get("UNIVERSE_SUPERVISOR_WATCH_STDIN"), False),
            lkg_stable_s=lkg_stable,
            boot_timeout_s=boot_timeout,
        )


def find_ollama() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if local.is_file():
            return str(local)
    return None
