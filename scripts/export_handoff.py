"""Build the handoff package: everything another AI (or a person) needs to take over UNIVERSE, as one folder
and one zip you can download, upload or attach (docs/HANDOFF.md, "Getting the project to another AI").

    uv run python scripts/export_handoff.py [--out dist/handoff] [--no-history]
    pnpm handoff

What's in it, all taken from one snapshot of the committed HEAD (uncommitted changes are left out, and the
script warns about them):

- 00-START-HERE.md: what this is, the current phase, the start prompt, which file to give which AI;
- universe-brief.md: the rules, the project brief, the owner's decisions and the handoff guide (small);
- universe-docs.md: the brief plus SPEC, the architecture, every phase record, ADR and proposal;
- universe-code.md: every source file as text (lockfiles and generated files are in the zip instead);
- universe-source.zip: the repository at HEAD, as files;
- universe-history.bundle: the full git history (`git clone universe-history.bundle universe`);
- SHA256SUMS.txt.

Standard library only.
"""

import argparse
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "claude/phase-0-delivery-zuqlfx"

BRIEF = [
    "AGENTS.md",
    "docs/handoff/PROJECT-BRIEF.md",
    "docs/handoff/DECISIONS.md",
    "docs/HANDOFF.md",
    "llms.txt",
]
DOCS_HEAD = ["README.md", "SPEC.md", "docs/ARCHITECTURE.md", "docs/VISION-neural-universe.md"]
DOCS_TAIL = ["protected-core.txt", "CLAUDE.md", ".github/copilot-instructions.md"]
# Lockfiles and generated files: in universe-source.zip, but they'd only bury the code in universe-code.md.
NOT_IN_CODE = (
    "pnpm-lock.yaml",
    "uv.lock",
    "packages/shared-types/openapi.json",
    "packages/shared-types/src/api.ts",
    "packages/shared-types/src/events.ts",
    "packages/design-tokens/generated/",
)
LANG = {
    ".py": "python", ".ts": "ts", ".tsx": "tsx", ".js": "js", ".mjs": "js", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".md": "markdown", ".sql": "sql", ".toml": "toml", ".css": "css", ".html": "html",
    ".sh": "sh", ".ps1": "powershell", ".patch": "diff", ".txt": "text",
}  # fmt: skip


FILE_GUIDE = [
    (
        "universe-brief.md",
        "Rules (AGENTS.md), the project brief, every owner decision verbatim, the handoff guide",
        "Any chat AI, first. Enough to understand and plan",
    ),
    (
        "universe-docs.md",
        "The brief plus SPEC, architecture, every phase record, ADR, proposal and agent definition",
        "Chat AIs with a large context, or as a project/knowledge file",
    ),
    (
        "universe-code.md",
        "Every source file as text, one section per file",
        "AIs that should read or review the code but can't open a zip",
    ),
    (
        "universe-source.zip",
        "The repository at this commit, as files",
        "Coding AIs and IDEs (Cursor, Windsurf, Cline, Copilot, Codex, Claude Code, Gemini CLI, Aider): unzip it",
    ),
    (
        "universe-history.bundle",
        "The full git history",
        "Anyone who needs history: `git clone universe-history.bundle universe`",
    ),
]


class ExportError(Exception):
    pass


@dataclass
class Snapshot:
    commit: str
    short: str
    date: str
    files: dict[str, bytes] = field(default_factory=dict)

    def text(self, path: str) -> str | None:
        data = self.files.get(path)
        if data is None or b"\x00" in data:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None


def git(repo: Path, *args: str) -> bytes:
    exe = shutil.which("git")
    if exe is None:
        raise ExportError("git is not installed")
    done = subprocess.run([exe, "-C", str(repo), *args], capture_output=True, check=False)
    if done.returncode != 0:
        raise ExportError(f"git {' '.join(args[:2])} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def snapshot(repo: Path) -> Snapshot:
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    date = git(repo, "show", "-s", "--format=%cd", "--date=format:%Y-%m-%d", "HEAD").decode().strip()
    snap = Snapshot(commit=commit, short=commit[:10], date=date)
    with tarfile.open(fileobj=io.BytesIO(git(repo, "archive", "--format=tar", "HEAD"))) as tar:
        for member in tar.getmembers():
            if member.isfile():
                extracted = tar.extractfile(member)
                if extracted is not None:
                    snap.files[member.name] = extracted.read()
    return snap


def fenced(path: str, text: str) -> str:
    """A file as a Markdown section, with a fence longer than any backtick run inside it."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    lang = LANG.get(Path(path).suffix, "")
    body = text if text.endswith("\n") else text + "\n"
    return f"## File: `{path}`\n\n{fence}{lang}\n{body}{fence}\n"


def pack(title: str, intro: str, snap: Snapshot, paths: list[str]) -> str:
    parts = [f"# {title}\n\n{intro}\n\nCommit `{snap.commit}` ({snap.date}), branch `{BRANCH}`.\n"]
    parts.append("Files in this pack:\n\n" + "\n".join(f"- `{p}`" for p in paths) + "\n")
    for path in paths:
        text = snap.text(path)
        if text is not None:
            parts.append(fenced(path, text))
    return "\n".join(parts)


def docs_paths(snap: Snapshot) -> list[str]:
    def under(prefix: str, suffix: str = ".md") -> list[str]:
        return sorted(p for p in snap.files if p.startswith(prefix) and p.endswith(suffix))

    phases = sorted(under("docs/PHASE-"), key=lambda p: [int(n) for n in re.findall(r"\d+", p)], reverse=True)
    agents = under("agents/", ".yaml") + under("agents/prompts/")
    proposals = [p for p in under("docs/proposals/") if p.count("/") == 2]
    ordered = [*BRIEF, *DOCS_HEAD, *phases, *under("docs/adr/"), *proposals, *agents, *DOCS_TAIL]
    return [p for p in dict.fromkeys(ordered) if p in snap.files]


def code_paths(snap: Snapshot) -> tuple[list[str], list[str]]:
    included, binary = [], []
    for path in sorted(snap.files):
        if any(path == x or (x.endswith("/") and path.startswith(x)) for x in NOT_IN_CODE):
            continue
        (included if snap.text(path) is not None else binary).append(path)
    return included, binary


def current_phase(agents_md: str) -> str:
    match = re.search(r"^\*\*Current phase:\*\*(.+)$", agents_md, re.MULTILINE)
    return match.group(1).strip() if match else "(see AGENTS.md)"


def start_prompt(handoff_md: str) -> str:
    section = handoff_md.split("## Start prompt", 1)[-1].split("\n## ", 1)[0]
    lines = [ln[2:] if ln.startswith("> ") else ln[1:] for ln in section.splitlines() if ln.startswith(">")]
    return " ".join(ln.strip() for ln in lines).strip()


def human_size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def start_here(snap: Snapshot, sizes: dict[str, int], history_note: str, binary: list[str]) -> str:
    def row(name: str, what: str, give: str) -> str:
        size = sizes.get(name)
        tokens = f" · ~{size // 4 // 1000}k tokens" if size and name.endswith(".md") else ""
        return f"| `{name}` | {human_size(size) if size else '—'}{tokens} | {what} | {give} |"

    agents_md = snap.text("AGENTS.md") or ""
    handoff_md = snap.text("docs/HANDOFF.md") or ""
    rows = "\n".join(row(*entry) for entry in FILE_GUIDE)
    return f"""# UNIVERSE handoff package

UNIVERSE is a local-first Windows desktop "digital brain": everything the owner has lives in one navigable 3D
universe, run by a team of local AI agents (Electron + React, Python/FastAPI, SQLite + LanceDB, Ollama). This
package holds the whole project as of commit `{snap.commit}` ({snap.date}) on branch `{BRANCH}` of the private
GitHub repository `skyslasher001/web5`.

**Current phase:** {current_phase(agents_md)}

## Which file to give which AI

| File | Size | What it is | Give it to |
| --- | --- | --- | --- |
{rows}
| `SHA256SUMS.txt` | — | Checksums of everything above | Check the files arrived intact |

{history_note}

Coding AIs that can connect to GitHub can instead be given access to `skyslasher001/web5` and told to use the
branch `{BRANCH}` (`main` holds an old, unrelated landing page).

## Start prompt (paste this with the files)

> {start_prompt(handoff_md)}

## The rules, in one breath

Never edit the protected core (`protected-core.txt`; propose a patch in `docs/proposals/` instead), never
disable or weaken a test, never delete or rewrite vault data, no secrets, outbound network only through the
egress gate, permissive licenses only, mic/screen/camera off by default, generated files only via `pnpm tokens`
and `pnpm gen:types`. The full list is in `AGENTS.md`.

## Not in the text packs

Lockfiles and generated files ({", ".join(f"`{x}`" for x in NOT_IN_CODE)}) and {len(binary)} binary file(s)
are only in `universe-source.zip`.
"""


def build(repo: Path, out: Path, *, history: bool = True) -> tuple[Path, Path]:
    """Write the package folder and its zip under `out`; returns (folder, zip)."""
    snap = snapshot(repo)
    name = f"universe-handoff-{snap.date}-{snap.short}"
    folder = out / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    brief = [p for p in BRIEF if p in snap.files]
    docs = docs_paths(snap)
    code, binary = code_paths(snap)
    (folder / "universe-brief.md").write_text(
        pack("UNIVERSE: brief pack", "Rules, project brief, owner decisions and handoff guide.", snap, brief),
        encoding="utf-8",
    )
    (folder / "universe-docs.md").write_text(
        pack("UNIVERSE: documentation pack", "Every document, the most important first.", snap, docs),
        encoding="utf-8",
    )
    (folder / "universe-code.md").write_text(
        pack("UNIVERSE: code pack", "Every source file at this commit, as text.", snap, code), encoding="utf-8"
    )
    (folder / "universe-source.zip").write_bytes(git(repo, "archive", "--format=zip", "--prefix=universe/", "HEAD"))

    shallow = git(repo, "rev-parse", "--is-shallow-repository").decode().strip() == "true"
    if not history:
        history_note = "The history bundle was left out on request (`--no-history`)."
    elif shallow:
        history_note = "No history bundle: this checkout is shallow, so its history is incomplete."
    else:
        git(repo, "bundle", "create", str(folder / "universe-history.bundle"), "--all")
        history_note = "`universe-history.bundle` holds every branch and commit."

    sizes = {p.name: p.stat().st_size for p in folder.iterdir()}
    (folder / "00-START-HERE.md").write_text(start_here(snap, sizes, history_note, binary), encoding="utf-8")
    sums = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
        for p in sorted(folder.iterdir())
        if p.name != "SHA256SUMS.txt"
    ]
    (folder / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

    archive = out / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.iterdir()):
            zf.write(p, f"{name}/{p.name}")
    return folder, archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "handoff")
    parser.add_argument("--no-history", action="store_true", help="leave out the git history bundle")
    args = parser.parse_args()
    dirty = git(ROOT, "status", "--porcelain", "--untracked-files=no").decode().strip()
    if dirty:
        print("warning: uncommitted changes are NOT in the package (it's built from HEAD):", file=sys.stderr)
        print(dirty, file=sys.stderr)
    try:
        folder, archive = build(ROOT, args.out, history=not args.no_history)
    except ExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Handoff package: {archive} ({human_size(archive.stat().st_size)})")
    for p in sorted(folder.iterdir()):
        print(f"  {p.name:28} {human_size(p.stat().st_size)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
