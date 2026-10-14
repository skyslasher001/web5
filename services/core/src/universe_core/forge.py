"""Forge (SPEC §9, ADR-0014): what needs fixing, where fixes are written, and the proposals you decide on.

- **Issues** come from grouped errors, failed background jobs, failing checks and your bug reports, deduplicated
  by fingerprint and ranked by severity, frequency and recency. Their text is untrusted (logs, stack traces).
- **Worktrees**: each proposal gets a git worktree on branch `forge/<id>` under `<data dir>/forge/`. Writes go
  only there: never outside it, never into `.git`, never to a protected path (`protected-core.txt`).
- **Proposals** keep the diff, its hash, the root cause, the verification report, the reviews and your decision
  forever. Forge can't approve or apply anything: approval happens in a native dialog in Electron main, and
  the supervisor applies (both protected core).
"""

import hashlib
import json
import math
import os
import shutil
import sqlite3
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from universe_common.ids import uuid7
from universe_common.schema import ApiModel
from universe_common.sqlite import connect, transaction
from universe_common.timeutil import utcnow

MANIFEST = "protected-core.txt"
DAILY_CAP = 5  # proposals per day (SPEC §9: "batched and rate-limited")
SEVERITY_WEIGHT = {"warning": 1.0, "error": 3.0, "critical": 9.0}

IssueStatus = Literal["open", "working", "proposed", "fixed", "ignored"]
ProposalStatus = Literal["draft", "verifying", "failed", "ready", "approved", "applied", "rolled_back", "rejected"]


class ForgeError(Exception):
    """A refused or failed Forge operation, with a message fit for the agent and for you."""


class ForgeIssue(ApiModel):
    id: str
    source: Literal["error", "job", "check", "report"]
    title: str
    detail: str
    severity: Literal["warning", "error", "critical"]
    count: int
    status: IssueStatus
    score: float
    first_seen: str
    last_seen: str
    proposal_id: str | None


class ProposalFile(ApiModel):
    path: str
    status: str  # git's letter: A, M, D, R…


class ForgeProposal(ApiModel):
    id: str
    issue_id: str | None
    task_id: str | None
    title: str
    root_cause: str
    branch: str
    base_commit: str
    head_commit: str | None
    diff: str
    diff_sha: str | None
    files: list[ProposalFile]
    repro_test: str | None
    verification: dict[str, Any]
    reviews: dict[str, Any]
    risk: Literal["low", "medium", "high"] | None
    rollback_plan: str
    touches_protected: bool
    status: ProposalStatus
    release: str | None
    created_at: str
    updated_at: str
    decided_at: str | None


# ---------- protected paths ----------


class ProtectedPaths:
    """The globs in `protected-core.txt` (one per line, `#` comments). The manifest itself is always protected."""

    def __init__(self, patterns: list[str]) -> None:
        self.patterns = sorted({*patterns, MANIFEST})

    @classmethod
    def load(cls, repo: Path) -> "ProtectedPaths":
        path = repo / MANIFEST
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        return cls([ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")])

    def matches(self, rel: str) -> bool:
        rel = PurePosixPath(rel.replace("\\", "/")).as_posix().lstrip("/")
        for pattern in self.patterns:
            if pattern.endswith("/**") and (rel == pattern[:-3] or rel.startswith(pattern[:-2])):
                return True
            if fnmatchcase(rel, pattern.replace("**", "*")):
                return True
        return False


# ---------- git ----------


def _git_env() -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "TMP", "TEMP", "LANG")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.update(
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME="Forge",
        GIT_AUTHOR_EMAIL="forge@universe.local",
        GIT_COMMITTER_NAME="Forge",
        GIT_COMMITTER_EMAIL="forge@universe.local",
    )
    return env


def git(repo: Path, *args: str, timeout: float = 120.0) -> str:
    exe = shutil.which("git")
    if exe is None:
        raise ForgeError("git is not installed")
    try:
        done = subprocess.run(
            [exe, "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_git_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ForgeError(f"git {args[0]} timed out") from exc
    if done.returncode != 0:
        raise ForgeError(f"git {' '.join(args[:2])} failed: {(done.stderr or done.stdout).strip()[:500]}")
    return done.stdout


# ---------- worktrees ----------


@dataclass
class Worktree:
    path: Path
    branch: str
    base: str
    protected: ProtectedPaths

    def resolve(self, rel: str) -> Path:
        """A path inside the worktree that Forge may write: not outside it, not `.git`, not protected."""
        clean = rel.replace("\\", "/").strip()
        if not clean or clean.startswith("/") or (len(clean) > 1 and clean[1] == ":"):
            raise ForgeError(f"'{rel}': use a path relative to the repository root")
        target = (self.path / clean).resolve()
        root = self.path.resolve()
        if target != root and root not in target.parents:
            raise ForgeError(f"'{rel}' is outside the repository")
        relative = target.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/") or "/.git/" in f"/{relative}/":
            raise ForgeError("Forge never writes inside .git")
        if self.protected.matches(relative):
            raise ForgeError(
                f"'{relative}' is protected core: Forge can't change it. Describe the change in the proposal "
                "and the owner applies it by hand."
            )
        return target

    def read(self, rel: str) -> str:
        target = (self.path / rel.replace("\\", "/")).resolve()
        if self.path.resolve() not in target.parents:
            raise ForgeError(f"'{rel}' is outside the repository")
        if not target.is_file():
            raise ForgeError(f"No file '{rel}'")
        return target.read_text(encoding="utf-8", errors="replace")

    def write(self, rel: str, content: str) -> str:
        target = self.resolve(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return target.relative_to(self.path.resolve()).as_posix()

    def commit(self, message: str) -> str:
        git(self.path, "add", "-A")
        if git(self.path, "status", "--porcelain").strip():
            git(self.path, "commit", "-q", "--no-verify", "-m", message)
        return git(self.path, "rev-parse", "HEAD").strip()

    def changes(self) -> list[ProposalFile]:
        out = git(self.path, "diff", "--name-status", f"{self.base}..HEAD")
        files = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                files.append(ProposalFile(path=parts[-1], status=parts[0][:1]))
        return files

    def diff(self) -> str:
        return git(self.path, "diff", "--no-color", f"{self.base}..HEAD")


def diff_sha(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


# ---------- the store ----------


def _score(severity: str, count: int, last_seen: str, now: datetime) -> float:
    age_days = max(0.0, (now - datetime.fromisoformat(last_seen)).total_seconds() / 86400)
    return round(SEVERITY_WEIGHT.get(severity, 1.0) * math.log2(1 + count) / (1 + age_days / 7), 3)


def fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:32]


class Forge:
    """Forge's store and worktrees. Its slow work (git, verification) runs in worker threads, so it keeps one
    connection per thread to universe.db instead of sharing the event loop's."""

    def __init__(self, db_path: Path, repo: Path | None, data_dir: Path) -> None:
        self._db_path = db_path
        self._local = threading.local()
        self.repo = repo
        self.root = data_dir / "forge"

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self._db_path)
            self._local.conn = conn
        return conn

    # ---------- state ----------

    @property
    def unavailable_reason(self) -> str | None:
        if self.repo is None:
            return "No codebase to repair: set UNIVERSE_REPO_DIR to a git checkout of UNIVERSE."
        if not (self.repo / ".git").exists():
            return f"{self.repo} is not a git checkout, so Forge can't open worktrees there."
        if shutil.which("git") is None:
            return "git is not installed."
        return None

    def protected(self) -> ProtectedPaths:
        return ProtectedPaths.load(self.require_repo())

    def require_repo(self) -> Path:
        reason = self.unavailable_reason
        if reason:
            raise ForgeError(reason)
        assert self.repo is not None
        return self.repo

    # ---------- issues ----------

    def sync_issues(self) -> int:
        """Pull new grouped errors and dead background jobs into the issue list. Returns how many changed."""
        now = utcnow()
        changed = 0
        with transaction(self._conn):
            for e in self._conn.execute(
                "SELECT fingerprint, service, kind, message, stack, severity, count, first_seen, last_seen"
                " FROM errors WHERE status NOT IN ('fixed', 'ignored')"
            ).fetchall():
                title = f"{e['service']}: {e['kind']}: {e['message'].splitlines()[0][:160] if e['message'] else ''}"
                changed += self._upsert(
                    "error", f"error:{e['fingerprint']}", title, f"{e['message']}\n\n{e['stack']}".strip(),
                    e["severity"], e["count"], e["first_seen"], e["last_seen"],
                )  # fmt: skip
            for j in self._conn.execute(
                "SELECT kind, error, COUNT(*) AS n, MIN(created_at) AS first, MAX(updated_at) AS last FROM jobs"
                " WHERE status = 'dead' AND error IS NOT NULL GROUP BY kind, error"
            ).fetchall():
                first_line = (j["error"] or "").splitlines()[0][:160]
                changed += self._upsert(
                    "job", fingerprint("job", j["kind"], first_line), f"Background job '{j['kind']}' keeps failing: "
                    f"{first_line}", j["error"] or "", "error", j["n"], j["first"] or now, j["last"] or now,
                )  # fmt: skip
        return changed

    def report(self, text: str, *, source: Literal["report", "check"] = "report") -> ForgeIssue:
        """Your bug report ("the photo viewer froze"), or a failing check, as an issue."""
        now = utcnow()
        title = text.strip().splitlines()[0][:160]
        fp = fingerprint(source, title.lower())
        with transaction(self._conn):
            self._upsert(source, fp, title, text.strip(), "error", 1, now, now)
        row = self._conn.execute("SELECT * FROM forge_issues WHERE fingerprint = ?", (fp,)).fetchone()
        return self._issue(row)

    def _upsert(
        self, source: str, fp: str, title: str, detail: str, severity: str, count: int, first: str, last: str
    ) -> int:
        row = self._conn.execute("SELECT id, count, status FROM forge_issues WHERE fingerprint = ?", (fp,)).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO forge_issues (id, source, fingerprint, title, detail, severity, count, first_seen,"
                " last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid7(), source, fp, title, detail[:20_000], severity, count, first, last),
            )
            return 1
        new_count = max(count, row["count"] + (1 if source in ("report", "check") else 0))
        if new_count == row["count"] and source not in ("report", "check"):
            return 0
        # It came back after a fix: open again.
        status = "open" if row["status"] == "fixed" else row["status"]
        self._conn.execute(
            "UPDATE forge_issues SET count = ?, last_seen = ?, detail = ?, status = ? WHERE id = ?",
            (new_count, last, detail[:20_000], status, row["id"]),
        )
        return 1

    def issues(self, status: str | None = None, limit: int = 100) -> list[ForgeIssue]:
        query = "SELECT * FROM forge_issues"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        rows = self._conn.execute(query, params).fetchall()
        issues = [self._issue(r) for r in rows]
        issues.sort(key=lambda i: (i.status != "open", -i.score))
        return issues[:limit]

    def issue(self, issue_id: str) -> ForgeIssue:
        row = self._conn.execute("SELECT * FROM forge_issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            raise ForgeError(f"No issue '{issue_id}'")
        return self._issue(row)

    def set_issue_status(self, issue_id: str, status: IssueStatus, proposal_id: str | None = None) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE forge_issues SET status = ?, proposal_id = COALESCE(?, proposal_id) WHERE id = ?",
                (status, proposal_id, issue_id),
            )

    def _issue(self, r: sqlite3.Row) -> ForgeIssue:
        return ForgeIssue(
            id=r["id"],
            source=r["source"],
            title=r["title"],
            detail=r["detail"],
            severity=r["severity"],
            count=r["count"],
            status=r["status"],
            score=_score(r["severity"], r["count"], r["last_seen"], datetime.now(UTC)),
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
            proposal_id=r["proposal_id"],
        )

    # ---------- worktrees and proposals ----------

    def proposals_today(self) -> int:
        since = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return int(
            self._conn.execute("SELECT COUNT(*) FROM forge_proposals WHERE created_at > ?", (since,)).fetchone()[0]
        )

    def start_proposal(
        self, *, title: str, issue_id: str | None, task_id: str | None
    ) -> tuple[ForgeProposal, Worktree]:
        """A draft proposal and its worktree on `forge/<id>`, branched from the repository's HEAD."""
        repo = self.require_repo()
        if self.proposals_today() >= DAILY_CAP:
            raise ForgeError(f"Forge already made {DAILY_CAP} proposals today (SPEC §9 rate limit). Try tomorrow.")
        proposal_id = uuid7()
        branch = f"forge/{proposal_id}"
        base = git(repo, "rev-parse", "HEAD").strip()
        path = self.root / "worktrees" / proposal_id
        path.parent.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", "-q", "-b", branch, str(path), base)
        now = utcnow()
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO forge_proposals (id, issue_id, task_id, title, branch, base_commit, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (proposal_id, issue_id, task_id, title.strip()[:200], branch, base, now, now),
            )
        if issue_id:
            self.set_issue_status(issue_id, "working", proposal_id)
        return self.proposal(proposal_id), Worktree(path, branch, base, self.protected())

    def worktree(self, proposal_id: str) -> Worktree:
        p = self.proposal(proposal_id)
        path = self.root / "worktrees" / proposal_id
        if not path.is_dir():
            raise ForgeError(f"The worktree for proposal {proposal_id} is gone")
        return Worktree(path, p.branch, p.base_commit, self.protected())

    def base_checkout(self, commit: str) -> Path:
        """A pristine, detached checkout of `commit` (where the repro test must fail)."""
        repo = self.require_repo()
        path = self.root / "base" / commit[:12]
        if not (path / ".git").exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            git(repo, "worktree", "add", "-q", "--detach", str(path), commit)
        else:
            git(path, "checkout", "-q", "--detach", "--force", commit)
            git(path, "clean", "-q", "-fdx", "-e", "node_modules")
        return path

    def proposal_for_task(self, task_id: str) -> ForgeProposal | None:
        row = self._conn.execute(
            "SELECT id FROM forge_proposals WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task_id,)
        ).fetchone()
        return self.proposal(row["id"]) if row else None

    def update(self, proposal_id: str, **fields: Any) -> ForgeProposal:
        allowed = {
            "title", "root_cause", "head_commit", "diff", "diff_sha", "files", "repro_test", "verification",
            "reviews", "risk", "rollback_plan", "touches_protected", "status", "release", "decided_at",
        }  # fmt: skip
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(key)
            if key in ("files", "verification", "reviews"):
                value = json.dumps(value, default=lambda m: m.model_dump() if hasattr(m, "model_dump") else str(m))
            sets.append(f"{key} = ?")
            params.append(int(value) if isinstance(value, bool) else value)
        sets.append("updated_at = ?")
        params.append(utcnow())
        with transaction(self._conn):
            self._conn.execute(
                f"UPDATE forge_proposals SET {', '.join(sets)} WHERE id = ?",  # noqa: S608 (fixed column names)
                (*params, proposal_id),
            )
        return self.proposal(proposal_id)

    def proposals(self, status: str | None = None, limit: int = 50) -> list[ForgeProposal]:
        query = "SELECT * FROM forge_proposals"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._proposal(r) for r in self._conn.execute(query, params).fetchall()]

    def proposal(self, proposal_id: str) -> ForgeProposal:
        row = self._conn.execute("SELECT * FROM forge_proposals WHERE id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise ForgeError(f"No proposal '{proposal_id}'")
        return self._proposal(row)

    def _proposal(self, r: sqlite3.Row) -> ForgeProposal:
        return ForgeProposal(
            id=r["id"],
            issue_id=r["issue_id"],
            task_id=r["task_id"],
            title=r["title"],
            root_cause=r["root_cause"],
            branch=r["branch"],
            base_commit=r["base_commit"],
            head_commit=r["head_commit"],
            diff=r["diff"],
            diff_sha=r["diff_sha"],
            files=[ProposalFile(**f) for f in json.loads(r["files"] or "[]")],
            repro_test=r["repro_test"],
            verification=json.loads(r["verification"] or "{}"),
            reviews=json.loads(r["reviews"] or "{}"),
            risk=r["risk"],
            rollback_plan=r["rollback_plan"],
            touches_protected=bool(r["touches_protected"]),
            status=r["status"],
            release=r["release"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            decided_at=r["decided_at"],
        )

    def discard_worktree(self, proposal_id: str) -> None:
        """Remove a rejected or failed proposal's worktree (its branch, diff and record stay)."""
        repo = self.require_repo()
        path = self.root / "worktrees" / proposal_id
        if path.exists():
            git(repo, "worktree", "remove", "--force", str(path))
