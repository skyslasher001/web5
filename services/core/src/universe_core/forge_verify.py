"""Forge's verification (SPEC §9 step 6, ADR-0014): the repro test must fail on the base commit and pass with the
patch; then lint, types and the test suites must pass. Core runs its own copy of this code, never the
worktree's, so a patch can't weaken the checks it is judged by.

Checks run as subprocesses in the worktree with a scrubbed environment: no tokens or UNIVERSE_* settings,
offline, proxies pointed at a dead port, a temporary home. That limits accidents; real isolation needs
containers (ADR-0014, flagged).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TAIL = 4000  # characters of output kept per check
DEAD_PROXY = "http://127.0.0.1:9"


@dataclass
class CheckResult:
    name: str
    command: list[str]
    ok: bool
    seconds: float
    output: str


@dataclass
class Report:
    repro: dict[str, Any] = field(default_factory=dict)  # {test, fails_on_base, passes_on_head, base, head}
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        repro_ok = bool(self.repro.get("fails_on_base")) and bool(self.repro.get("passes_on_head"))
        return repro_ok and all(c.ok for c in self.checks)

    def summary(self) -> str:
        lines = []
        if self.repro:
            lines.append(
                f"Repro test {self.repro.get('test')}: fails on base: {self.repro.get('fails_on_base')}, "
                f"passes with the patch: {self.repro.get('passes_on_head')}"
            )
        lines += [f"{'PASS' if c.ok else 'FAIL'} {c.name} ({c.seconds:.1f} s)" for c in self.checks]
        failed = [c for c in self.checks if not c.ok]
        for c in failed[:2]:
            lines.append(f"\n--- {c.name} output ---\n{c.output[-1500:]}")
        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {"passed": self.passed, "repro": self.repro, "checks": [asdict(c) for c in self.checks]}


def python_paths(tree: Path) -> list[str]:
    """Source roots of a checkout: UNIVERSE's services/*/src, else the checkout itself."""
    roots = sorted(str(p) for p in tree.glob("services/*/src") if p.is_dir())
    return [*roots, str(tree)] if roots else [str(tree)]


def scrubbed_env(tree: Path, home: Path) -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "PLAYWRIGHT_BROWSERS_PATH")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        TMP=str(home),
        TEMP=str(home),
        PYTHONPATH=os.pathsep.join(python_paths(tree)),
        PYTHONDONTWRITEBYTECODE="1",
        UNIVERSE_OFFLINE="1",
        HTTP_PROXY=DEAD_PROXY,
        HTTPS_PROXY=DEAD_PROXY,
        http_proxy=DEAD_PROXY,
        https_proxy=DEAD_PROXY,
        NO_PROXY="",
        CI="1",
    )
    return env


def run(name: str, command: list[str], cwd: Path, env: dict[str, str], timeout: float) -> CheckResult:
    started = time.monotonic()
    try:
        done = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False)
        ok, output = done.returncode == 0, (done.stdout + done.stderr)
    except subprocess.TimeoutExpired as exc:
        ok, output = False, f"timed out after {timeout:.0f} s\n{exc.stdout or ''}"
    except OSError as exc:
        ok, output = False, f"could not run: {exc}"
    return CheckResult(name, command, ok, round(time.monotonic() - started, 2), str(output)[-TAIL:])


def link_node_modules(repo: Path, tree: Path) -> None:
    """JS checks in a worktree use the repository's installed packages (a worktree has none of its own)."""
    for nm in [repo / "node_modules", *repo.glob("apps/*/node_modules"), *repo.glob("packages/*/node_modules")]:
        if not nm.is_dir():
            continue
        target = tree / nm.relative_to(repo)
        if target.exists() or not target.parent.is_dir():
            continue
        try:
            target.symlink_to(nm, target_is_directory=True)
        except OSError:  # Windows without symlink rights: a junction would need admin-free mklink /J
            subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(nm)], capture_output=True, check=False)


class Verifier:
    def __init__(self, repo: Path, *, python: str | None = None, timeout_s: float = 900.0) -> None:
        self.repo = repo
        self.python = python or sys.executable
        self.timeout_s = timeout_s

    def repro(self, base: Path, head: Path, test: str) -> dict[str, Any]:
        """Copy the repro test into the base checkout and run it in both: it must fail there and pass here."""
        rel = test.split("::", 1)[0]
        source = head / rel
        if not source.is_file():
            return {"test": test, "fails_on_base": False, "passes_on_head": False, "error": f"no file {rel}"}
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        command = [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", test]
        with tempfile.TemporaryDirectory(prefix="forge-home-") as home:
            on_base = run("repro on base", command, base, scrubbed_env(base, Path(home)), self.timeout_s)
            on_head = run("repro with the patch", command, head, scrubbed_env(head, Path(home)), self.timeout_s)
        dest.unlink(missing_ok=True)  # the base checkout stays pristine
        return {
            "test": test,
            "fails_on_base": not on_base.ok,
            "passes_on_head": on_head.ok,
            "base": asdict(on_base),
            "head": asdict(on_head),
        }

    def checks(self, head: Path, changed: list[str]) -> list[CheckResult]:
        """Lint and types on what changed, then the test suites. JS checks only when JS changed."""
        results: list[CheckResult] = []
        py = [f for f in changed if f.endswith(".py") and (head / f).is_file()]
        js = [f for f in changed if f.endswith((".ts", ".tsx", ".js", ".mjs")) and (head / f).is_file()]
        venv = self.repo / ".venv"
        if venv.is_dir() and not (head / ".venv").exists():
            try:
                (head / ".venv").symlink_to(venv, target_is_directory=True)  # pyright finds the packages there
            except OSError:  # Windows without symlink rights: a junction needs no admin (as in link_node_modules)
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(head / ".venv"), str(venv)], capture_output=True, check=False
                )
        with tempfile.TemporaryDirectory(prefix="forge-home-") as home:
            env = scrubbed_env(head, Path(home))
            if py and _has_module(self.python, "ruff"):
                results.append(run("ruff check", [self.python, "-m", "ruff", "check", *py], head, env, 300))
                results.append(
                    run("ruff format", [self.python, "-m", "ruff", "format", "--check", *py], head, env, 300)
                )
            if py and _has_module(self.python, "pyright") and (head / "pyproject.toml").is_file():
                results.append(run("pyright", [self.python, "-m", "pyright", *py], head, env, 600))
            tests_dir = "tests" if (head / "tests").is_dir() else "."
            results.append(
                run(
                    "pytest (full suite)",
                    [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", tests_dir],
                    head,
                    env,
                    self.timeout_s,
                )
            )
            if js and (self.repo / "node_modules").is_dir():
                link_node_modules(self.repo, head)
                pnpm = shutil.which("pnpm") or "pnpm"
                results.append(run("eslint", [pnpm, "exec", "eslint", *js], head, env, 600))
                results.append(run("vitest", [pnpm, "exec", "vitest", "run"], head, env, 900))
                results.append(run("typecheck", [pnpm, "-r", "typecheck"], head, env, 900))
        return results


def _has_module(python: str, name: str) -> bool:
    done = subprocess.run(
        [python, "-c", f"import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('{name}') else 1)"],
        capture_output=True,
        check=False,
    )
    return done.returncode == 0
