"""Releases: apply an approved Forge proposal, watch it, roll it back (SPEC §9, ARCHITECTURE §7, ADR-0014).

Only Electron main can ask (it holds the control token, and only after you confirm in a native dialog). Before
applying, the supervisor checks everything itself rather than trusting Core or the renderer:

- your checkout has no uncommitted changes (nothing of yours can be lost);
- the proposal's branch tip is exactly the verified commit, and the code hasn't moved since its base;
- the diff's hash matches the one you were shown;
- no changed path is protected core, judged by the supervisor's **own copy** of `protected-core.txt`, read
  when it started (and the manifest in the checkout must still match that copy).

Applying is a fast-forward merge between two tags; rolling back adds revert commits (history is never
rewritten). State is a JSON file written atomically, like the rest of the supervisor's. Standard library only.
"""

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

MANIFEST = "protected-core.txt"
WATCH_S = 30 * 60.0  # ARCHITECTURE §7.2: watch for 30 minutes after applying


class ReleaseError(Exception):
    pass


def _patterns(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    return sorted({*(ln for ln in lines if ln and not ln.startswith("#")), MANIFEST})


def protected(rel: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/**") and (rel == pattern[:-3] or rel.startswith(pattern[:-2])):
            return True
        if fnmatchcase(rel, pattern.replace("**", "*")):
            return True
    return False


class Releases:
    def __init__(self, repo: Path, state_path: Path, *, watch_s: float = WATCH_S) -> None:
        self.repo = repo
        self.path = state_path
        self.watch_s = watch_s
        self._lock = threading.Lock()
        manifest = repo / MANIFEST
        text = manifest.read_text(encoding="utf-8") if manifest.is_file() else ""
        self.manifest_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.patterns = _patterns(text)  # the supervisor's own copy, fixed for its lifetime
        self.data: dict[str, Any] = {"releases": []}
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("releases"), list):
                self.data = loaded
        except (OSError, ValueError):
            pass

    # ---------- git ----------

    def _git(self, *args: str, timeout: float = 120.0) -> str:
        exe = shutil.which("git")
        if exe is None:
            raise ReleaseError("git is not installed")
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "HOME", "USERPROFILE", "LANG")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_AUTHOR_NAME="UNIVERSE", GIT_AUTHOR_EMAIL="supervisor@universe.local",
                   GIT_COMMITTER_NAME="UNIVERSE", GIT_COMMITTER_EMAIL="supervisor@universe.local")  # fmt: skip
        try:
            done = subprocess.run(
                [exe, "-C", str(self.repo), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",  # not the ANSI code page on Windows (-I ignores PYTHONUTF8); same as Core's
                errors="replace",
                timeout=timeout,
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseError(f"git {args[0]} failed: {exc}") from exc
        if done.returncode != 0:
            raise ReleaseError(f"git {' '.join(args[:2])} failed: {(done.stderr or done.stdout).strip()[:300]}")
        return done.stdout

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    # ---------- state ----------

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[dict[str, Any]]:
        try:
            head = self.head()
        except ReleaseError:
            head = ""
        return [{**r, "current": r["commit"] == head and r["status"] != "rolled_back"} for r in self.data["releases"]]

    def watching(self) -> dict[str, Any] | None:
        return next((r for r in self.data["releases"] if r["status"] == "watching"), None)

    # ---------- apply ----------

    def apply(
        self, *, proposal_id: str, branch: str, base_commit: str, head_commit: str, diff_sha: str, title: str
    ) -> dict[str, Any]:
        with self._lock:
            if self.watching() is not None:
                raise ReleaseError("Another change is still being watched; wait until it settles or roll it back")
            if self._git("status", "--porcelain", "--untracked-files=no").strip():
                raise ReleaseError("The checkout has uncommitted changes: commit or stash them first")
            manifest = self.repo / MANIFEST
            text = manifest.read_text(encoding="utf-8") if manifest.is_file() else ""
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != self.manifest_sha:
                raise ReleaseError("protected-core.txt changed since the supervisor started: restart the app first")
            if not branch.startswith("forge/"):
                raise ReleaseError("Only Forge branches can be applied")
            tip = self._git("rev-parse", f"refs/heads/{branch}").strip()
            if tip != head_commit:
                raise ReleaseError("The branch moved after it was verified")
            head = self.head()
            if head != base_commit:
                raise ReleaseError("The code moved on since Forge started: ask Forge to redo the fix")
            # --text, as Core's Worktree.diff: a "binary" file can't hide its content (and the hashes agree).
            diff = self._git("diff", "--no-color", "--text", f"{base_commit}..{head_commit}")
            if hashlib.sha256(diff.encode("utf-8")).hexdigest() != diff_sha:
                raise ReleaseError("The change isn't the one you approved (its hash differs)")
            # --no-renames: list both sides of a rename, so renaming a protected file to an unprotected path
            # can't slip the protected source past this gate (git's rename detection would show only the dest).
            paths = [
                p
                for p in self._git("diff", "--name-only", "--no-renames", f"{base_commit}..{head_commit}").splitlines()
                if p
            ]
            touched = [p for p in paths if protected(p, self.patterns)]
            if touched:
                raise ReleaseError(f"It changes protected core ({', '.join(touched)}): apply those by hand")
            summary = self._git("diff", "--summary", "--no-renames", f"{base_commit}..{head_commit}")
            if " mode 120000 " in summary or "=> 120000" in summary:
                raise ReleaseError("It adds or changes a symbolic link: Forge changes never do")
            n = len(self.data["releases"]) + 1
            tag = f"universe/release-{n}"
            self._git("merge", "--ff-only", "-q", head_commit)
            # Tag after the merge succeeds: a failed ff-merge then leaves no dangling pre-release-n tag that
            # would block retrying release n. `head` (the prior HEAD) is still what rollback reverts to.
            self._git("tag", f"universe/pre-release-{n}", head)
            self._git("tag", tag, head_commit)
            release = {
                "tag": tag,
                "commit": head_commit,
                "previous": head,
                "proposal_id": proposal_id,
                "title": title[:200],
                "created_at": time.time(),
                "watch_until": time.time() + self.watch_s,
                "status": "watching",
                "rollback_reason": None,
            }
            self.data["releases"].append(release)
            self._save()
            return release

    # ---------- rollback ----------

    def rollback(self, tag: str, reason: str) -> dict[str, Any]:
        """Undo a release with revert commits (anything committed after it stays)."""
        with self._lock:
            release = next((r for r in self.data["releases"] if r["tag"] == tag), None)
            if release is None:
                raise ReleaseError(f"No release {tag}")
            if release["status"] == "rolled_back":
                raise ReleaseError(f"{tag} is already rolled back")
            if self._git("status", "--porcelain", "--untracked-files=no").strip():
                raise ReleaseError("The checkout has uncommitted changes: commit or stash them first")
            try:
                self._git("revert", "--no-edit", f"{release['previous']}..{release['commit']}")
            except ReleaseError:
                # A conflict (you changed the same lines since): leave the checkout as it was, and stop the
                # watch so it doesn't retry every tick; the owner rolls back by hand.
                with contextlib.suppress(ReleaseError):
                    self._git("revert", "--abort")
                release["status"] = "rollback_failed"
                release["rollback_reason"] = f"{reason}; the revert conflicted, so nothing was changed"
                self._save()
                raise
            release["status"] = "rolled_back"
            release["rollback_reason"] = reason
            release["rolled_back_at"] = time.time()
            self._save()
            return release

    def settle(self, tag: str) -> None:
        """The watch window passed without trouble."""
        with self._lock:
            for r in self.data["releases"]:
                if r["tag"] == tag and r["status"] == "watching":
                    r["status"] = "good"
            self._save()
