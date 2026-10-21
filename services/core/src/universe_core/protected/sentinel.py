"""Sentinel's deterministic review of a Forge proposal (SPEC §9, ARCHITECTURE §7.2, ADR-0014). Protected core.

A proposal reaches the owner only if this passes. It reads the diff, not the model's description of it:

- **block**: touches protected core; deletes, skips or weakens a test (fewer assertions, `skip`/`xfail`/`.only`);
  adds network code outside the egress gate; raises an agent's permission tier; addresses the reviewers.
- **high risk** (allowed, flagged): dependency or lockfile changes, database migrations, new subprocess or
  dynamic-code calls, consent and capture code, agent tool lists.
- **medium**: large diffs (over 200 changed lines).

Standard library only, deterministic, no model calls.
"""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from typing import Any

TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$|[^/]*\.(test|spec)\.[jt]sx?$)")
SKIPS = re.compile(
    r"pytest\.mark\.(skip|skipif|xfail)|pytest\.(skip|xfail)\(|unittest\.skip|"
    r"\b(it|test|describe)\.(skip|only|todo)\(|\bx(it|describe)\(|\.only\("
)
ASSERTS = re.compile(r"\bassert\b|\bexpect\(|\bpytest\.raises\(|\bself\.assert\w+\(")
TEST_DEF = re.compile(r"^\s*(async\s+)?def\s+test_\w+|^\s*(it|test)\(")
# Aligned with (and wider than) tests/protected/test_invariants.HTTP_CLIENT_MODULES so Sentinel's block list is
# never weaker than the project's own egress invariant: every stdlib/third-party client the project bans, plus
# the JS clients, plus a raw non-loopback URL.
NETWORK = re.compile(
    r"\b(?:import|from)\s+(?:httpx|requests|aiohttp|urllib3|socket|smtplib|ftplib|telnetlib|websockets?)\b|"
    r"\burllib\.request\b|\bhttp\.client\b|\basyncio\.open_connection\b|"
    r"\bfetch\(|XMLHttpRequest|new\s+WebSocket\(|\bEventSource\(|\baxios\b|"
    r"\b(?:https?|net)\.(?:get|request)\(|navigator\.sendBeacon|"
    r"https?://(?!127\.0\.0\.1|localhost)"
)
PROCESS = re.compile(r"\bsubprocess\b|\bos\.system\(|\bos\.popen\(|\beval\(|\bexec\(|child_process|\bspawn\(")
CAPTURE = re.compile(r"getUserMedia|desktopCapturer|microphone|\bconsent\b|screen.?capture|\bwebcam\b", re.I)
INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior) instructions|"
    r"\b(dear|hey|attention|note to)\s+(the\s+)?(sentinel|critic|reviewers?)\b|"
    r"\b(sentinel|critic|reviewers?)\s*,\s*(please|approve|pass|allow)",
    re.I,
)
DEPENDENCY_FILES = re.compile(r"(^|/)(pyproject\.toml|package\.json|uv\.lock|pnpm-lock\.yaml|requirements[^/]*\.txt)$")
EGRESS_MODULE = "services/common/src/universe_common/egress.py"
TIERS = {"read": 0, "write": 1, "system": 2}


@dataclass
class Finding:
    rule: str
    severity: str  # block | high | medium
    file: str
    detail: str


def _matches(rel: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/**") and (rel == pattern[:-3] or rel.startswith(pattern[:-2])):
            return True
        if fnmatchcase(rel, pattern.replace("**", "*")):
            return True
    return False


def _hunks(diff: str) -> dict[str, tuple[list[str], list[str]]]:
    """file → (added lines, removed lines), from a unified diff."""
    out: dict[str, tuple[list[str], list[str]]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" b/", 1)
            current = parts[1] if len(parts) == 2 else None
            if current is not None:
                out.setdefault(current, ([], []))
        elif current is None or line.startswith(("+++", "---")):
            continue
        elif line.startswith("+"):
            out[current][0].append(line[1:])
        elif line.startswith("-"):
            out[current][1].append(line[1:])
    return out


def review(*, diff: str, files: list[dict[str, str]], protected_patterns: list[str]) -> dict[str, Any]:
    findings: list[Finding] = []
    statuses = {f["path"]: f.get("status", "M") for f in files}
    hunks = _hunks(diff)
    changed_lines = 0
    for path in sorted(set(statuses) | set(hunks)):
        added, removed = hunks.get(path, ([], []))
        changed_lines += len(added) + len(removed)
        status = statuses.get(path, "M")
        if _matches(path, protected_patterns):
            findings.append(Finding("protected-core", "block", path, "changes protected core"))
        if TEST_FILE.search(path):
            if status == "D":
                findings.append(Finding("test-deleted", "block", path, "deletes a test file"))
            if status == "R":
                findings.append(Finding("test-renamed", "block", path, "renames a test file"))
            if any(SKIPS.search(a) for a in added):
                findings.append(Finding("test-skipped", "block", path, "adds skip, xfail, only or todo"))
            removed_tests = sum(bool(TEST_DEF.search(r)) for r in removed)
            added_tests = sum(bool(TEST_DEF.search(a)) for a in added)
            if removed_tests > added_tests:
                findings.append(
                    Finding("test-removed", "block", path, f"removes {removed_tests - added_tests} test(s)")
                )
            removed_asserts = sum(len(ASSERTS.findall(r)) for r in removed)
            added_asserts = sum(len(ASSERTS.findall(a)) for a in added)
            if removed_asserts > added_asserts:
                findings.append(
                    Finding(
                        "assertions-loosened", "block", path, f"{removed_asserts - added_asserts} fewer assertion(s)"
                    )
                )
        if path != EGRESS_MODULE and not TEST_FILE.search(path) and any(NETWORK.search(a) for a in added):
            findings.append(Finding("network", "block", path, "adds network code outside the egress gate"))
        if any(INJECTION.search(a) for a in added):
            findings.append(Finding("addresses-reviewers", "block", path, "contains text aimed at the reviewers"))
        if DEPENDENCY_FILES.search(path):
            findings.append(
                Finding("dependencies", "high", path, "changes dependencies: check licences and advisories")
            )
        if "/migrations/" in f"/{path}":
            findings.append(Finding("migration", "high", path, "a schema migration: needs a verified backup first"))
        if not TEST_FILE.search(path) and any(PROCESS.search(a) for a in added):
            findings.append(Finding("process", "high", path, "adds subprocess or dynamic-code calls"))
        if any(CAPTURE.search(a) for a in added):
            findings.append(Finding("capture", "high", path, "touches consent or capture code"))
        if re.match(r"agents/[^/]+\.ya?ml$", path):
            old = next((m.group(1) for r in removed if (m := re.search(r"permission_tier:\s*(\w+)", r))), None)
            new = next((m.group(1) for a in added if (m := re.search(r"permission_tier:\s*(\w+)", a))), None)
            if new and TIERS.get(new, 0) > TIERS.get(old or "read", 0):
                findings.append(Finding("permission-raised", "block", path, f"raises a permission tier to {new}"))
            if any(a.lstrip().startswith("tools:") for a in added) or any("tools:" in r for r in removed):
                findings.append(Finding("agent-tools", "high", path, "changes an agent's tools"))
            if any("requires_approval" in r for r in removed) or any(
                re.search(r"requires_approval:\s*\[\s*\]", a) for a in added
            ):
                findings.append(
                    Finding("agent-approvals", "high", path, "narrows or clears an agent's required approvals")
                )
    if changed_lines > 200:
        findings.append(Finding("size", "medium", "", f"{changed_lines} changed lines"))
    severities = {f.severity for f in findings}
    risk = "high" if severities & {"block", "high"} else "medium" if "medium" in severities else "low"
    return {
        "available": True,
        "verdict": "block" if "block" in severities else "pass",
        "risk": risk,
        "findings": [asdict(f) for f in findings],
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
