"""Last-known-good code via git (dev checkouts). Installed builds get their own scheme in Phase 12."""

import shutil
import subprocess
from pathlib import Path

PYTHON_PACKAGES = ("core", "common", "agents", "models")


def _git(repo: Path, *args: str, timeout: float = 30.0) -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(
            [git, "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def current_commit(repo: Path) -> str | None:
    commit = _git(repo, "rev-parse", "HEAD")
    return commit if commit and len(commit) == 40 else None


def prepare_worktree(repo: Path, path: Path, commit: str) -> bool:
    """Make `path` a detached worktree at `commit`. Returns True when it is ready."""
    if (path / ".git").exists():
        if _git(path, "checkout", "--detach", "--force", commit) is None:
            return False
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        if _git(repo, "worktree", "add", "--detach", "--force", str(path), commit, timeout=120.0) is None:
            return False
    return current_commit(path) == commit


def lkg_pythonpath(worktree: Path) -> list[str]:
    return [str(worktree / "services" / name / "src") for name in PYTHON_PACKAGES]
