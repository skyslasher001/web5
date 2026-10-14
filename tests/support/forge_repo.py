"""A tiny git repository with a deliberately injected bug, for Forge's tests (Phase 5 done-when). Forge works on
this scratch repository in tests, never on the real UNIVERSE checkout."""

import os
import subprocess
from pathlib import Path

BUGGY = '''"""Arithmetic the app relies on."""


def add(a: int, b: int) -> int:
    return a - b  # the injected bug: it should be a + b


def double(a: int) -> int:
    return a * 2
'''

FIXED = BUGGY.replace("return a - b  # the injected bug: it should be a + b", "return a + b")

EXISTING_TEST = """from calc import double


def test_double() -> None:
    assert double(4) == 8
"""

REPRO_TEST = """from calc import add


def test_add_adds() -> None:
    assert add(2, 3) == 5
"""

MANIFEST = """# Paths Forge may never modify.
protected-core.txt
services/supervisor/**
agents/forge.yaml
tests/protected/**
"""


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Owner",
        "GIT_AUTHOR_EMAIL": "owner@example.com",
        "GIT_COMMITTER_NAME": "Owner",
        "GIT_COMMITTER_EMAIL": "owner@example.com",
    }
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True)
    return done.stdout


def make_repo(root: Path) -> Path:
    """`root/app`: a committed project whose `add` subtracts. Returns the repository path."""
    repo = root / "app"
    (repo / "calc").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "services" / "supervisor").mkdir(parents=True)
    (repo / "calc" / "__init__.py").write_text(BUGGY, encoding="utf-8")
    (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "tests" / "test_double.py").write_text(EXISTING_TEST, encoding="utf-8")
    (repo / "services" / "supervisor" / "run.py").write_text("print('supervisor')\n", encoding="utf-8")
    (repo / "protected-core.txt").write_text(MANIFEST, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Initial commit with an injected bug")
    return repo


def head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()
