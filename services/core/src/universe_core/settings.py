"""Core configuration from environment variables (set by the supervisor)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from universe_common.egress import is_loopback
from universe_common.paths import default_data_dir, default_vault_dir, find_repo_root

DEFAULT_PORT = 47821
DEFAULT_ORIGINS = ("app://universe",)


class SettingsError(ValueError):
    pass


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CoreSettings:
    session_token: str
    port: int = DEFAULT_PORT
    allowed_origins: tuple[str, ...] = DEFAULT_ORIGINS
    data_dir: Path = Path()
    vault_dir: Path = Path()
    agents_dir: Path = Path()
    ollama_url: str = "http://127.0.0.1:11434"
    model_override: str | None = None
    safe_mode: bool = False
    offline: bool = False
    log_console: bool = True
    start_reason: str = "boot"  # boot|crash|health|manual|boot-retry|safe-mode (set by the supervisor)
    restart_count: int = 0
    last_exit: str = ""
    workers: int = 1  # pipeline worker processes (0 = none; tests drain the queue in-process)

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def index_dir(self) -> Path:
        """App index inside the vault (dot-folder, ignored by Obsidian)."""
        return self.vault_dir / ".universe"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "CoreSettings":
        env = os.environ if env is None else env
        token = env.get("UNIVERSE_SESSION_TOKEN", "")
        if len(token) < 32:
            raise SettingsError("UNIVERSE_SESSION_TOKEN must be set to at least 32 characters (the supervisor sets it)")
        try:
            port = int(env.get("UNIVERSE_CORE_PORT", DEFAULT_PORT))
        except ValueError as exc:
            raise SettingsError("UNIVERSE_CORE_PORT must be an integer") from exc
        if not 1024 <= port <= 65535:
            raise SettingsError("UNIVERSE_CORE_PORT must be between 1024 and 65535")
        origins = tuple(o.strip() for o in env.get("UNIVERSE_ALLOWED_ORIGINS", "").split(",") if o.strip())
        ollama_url = env.get("UNIVERSE_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        if not is_loopback(urlparse(ollama_url).hostname or ""):
            raise SettingsError("UNIVERSE_OLLAMA_URL must point at a loopback address")
        try:
            workers = int(env.get("UNIVERSE_WORKERS", "1"))
        except ValueError as exc:
            raise SettingsError("UNIVERSE_WORKERS must be an integer") from exc
        if not 0 <= workers <= 8:
            raise SettingsError("UNIVERSE_WORKERS must be between 0 and 8")
        repo = find_repo_root()
        agents_default = repo / "agents" if repo else Path("agents")
        return cls(
            session_token=token,
            port=port,
            allowed_origins=origins or DEFAULT_ORIGINS,
            data_dir=Path(env.get("UNIVERSE_DATA_DIR") or default_data_dir()),
            vault_dir=Path(env.get("UNIVERSE_VAULT_DIR") or default_vault_dir()),
            agents_dir=Path(env.get("UNIVERSE_AGENTS_DIR") or agents_default),
            ollama_url=ollama_url,
            model_override=env.get("UNIVERSE_MODEL_FAST") or None,
            safe_mode=_flag(env.get("UNIVERSE_SAFE_MODE")),
            offline=_flag(env.get("UNIVERSE_OFFLINE")),
            log_console=not _flag(env.get("UNIVERSE_LOG_QUIET")),
            start_reason=env.get("UNIVERSE_START_REASON") or "boot",
            restart_count=int(env.get("UNIVERSE_RESTART_COUNT") or 0),
            last_exit=env.get("UNIVERSE_LAST_EXIT") or "",
            workers=workers,
        )
