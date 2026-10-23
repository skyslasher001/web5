"""Default locations for app runtime data and the vault."""

import os
import sys
from pathlib import Path


def default_data_dir() -> Path:
    """App runtime data (logs, supervisor state). Not user data."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Universe"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "universe"


def default_vault_dir() -> Path:
    return Path.home() / "UniverseVault"


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` to the directory holding SPEC.md and pnpm-workspace.yaml."""
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "pnpm-workspace.yaml").is_file():
            return candidate
    return None
