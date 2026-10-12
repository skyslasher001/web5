"""Static invariants that keep the protected core and the egress model honest (ARCHITECTURE.md §1.3, §7)."""

import ast
import os
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

from tests.conftest import REPO

SERVICES = REPO / "services"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_supervisor_imports_only_the_standard_library() -> None:
    allowed = set(sys.stdlib_module_names) | {"universe_supervisor"}
    for path in (SERVICES / "supervisor").rglob("*.py"):
        for name in _imports(path):
            assert name.split(".")[0] in allowed, f"{path.relative_to(REPO)} imports {name}"


def test_supervisor_starts_without_site_packages() -> None:
    entry = SERVICES / "supervisor" / "run_supervisor.py"
    env = {"PATH": ""}
    if "SYSTEMROOT" in os.environ:  # Windows needs it for the interpreter to start at all
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(entry)], capture_output=True, text=True, timeout=30, env=env
    )
    assert result.returncode == 2, result.stderr  # config error, not ImportError
    assert "UNIVERSE_SUPERVISOR_TOKEN" in result.stderr


HTTP_CLIENT_MODULES = {"httpx", "requests", "aiohttp", "urllib.request", "http.client", "urllib3", "socket"}
EGRESS_EXEMPT = {
    "services/common/src/universe_common/egress.py": {"httpx"},  # the gate itself
    "services/supervisor/src/universe_supervisor/health.py": {"urllib.request"},  # loopback-only health checks
}
TYPE_ONLY = {"httpx"}  # importing httpx for exception and type names is fine; creating clients is not


def test_no_http_clients_outside_the_egress_gate() -> None:
    for path in SERVICES.rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if "/tests/" in rel:
            continue
        exempt = EGRESS_EXEMPT.get(rel, set())
        for name in _imports(path):
            if name in HTTP_CLIENT_MODULES and name not in exempt:
                assert name in TYPE_ONLY, f"{rel} imports {name}; outbound HTTP must go through the egress gate"
        if rel not in EGRESS_EXEMPT:
            source = path.read_text(encoding="utf-8")
            for call in ("httpx.AsyncClient(", "httpx.Client(", "httpx.get(", "httpx.post(", "httpx.stream("):
                assert call not in source, f"{rel} creates an HTTP client directly ({call})"


def test_protected_manifest_covers_the_protected_core() -> None:
    lines = (REPO / "protected-core.txt").read_text(encoding="utf-8").splitlines()
    globs = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    required = [
        "protected-core.txt",
        "services/supervisor/run_supervisor.py",
        "services/supervisor/src/universe_supervisor/supervisor.py",
        "services/core/src/universe_core/protected/audit.py",
        "apps/desktop/src/main/protected/supervisor.ts",
        "apps/desktop/src/safe-mode/index.html",
        "tests/protected/test_invariants.py",
        ".github/workflows/ci.yml",
        ".pre-commit-config.yaml",
        "agents/forge.yaml",
        "agents/sentinel.yaml",
    ]
    for path in required:
        assert any(fnmatch(path, g) for g in globs), f"{path} is not covered by protected-core.txt"
    for path in required[:7]:
        assert (REPO / path).exists(), f"protected file {path} is missing"
