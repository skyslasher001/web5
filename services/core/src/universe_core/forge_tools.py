"""Forge's tools (SPEC §9, ADR-0014). Forge can read the codebase and the issues, open a worktree, write in it,
run the verification and open a proposal. **No tool merges, applies or approves anything**: that happens only
in the supervisor, after you approve in a native dialog (protected core).

Worktree writes and verification change nothing outside Forge's own sandbox (`<data dir>/forge/`), so they
don't count as side effects for the policy engine. Issue text (logs, stack traces, your words) is untrusted.
"""

import asyncio
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from universe_agents.tools import Tool, ToolContext, ToolResult
from universe_core.forge import Forge, ForgeError, ForgeProposal, diff_sha, git
from universe_core.forge_verify import Report, Verifier

if TYPE_CHECKING:
    from universe_core.context import CoreContext

SENTINEL_MODULE = "universe_core.protected.sentinel"
NO_SENTINEL = (
    "Sentinel isn't installed yet (it is protected core: docs/proposals/phase-5-protected-core.md). "
    "Proposals can't be approved without its review."
)
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def load_sentinel() -> ModuleType | None:
    try:
        return importlib.import_module(SENTINEL_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != SENTINEL_MODULE:
            raise
        return None


class IssuesArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


class IssueArgs(BaseModel):
    issue_id: str = Field(min_length=8, max_length=64)


class RepoSearchArgs(BaseModel):
    pattern: str = Field(min_length=2, max_length=200, description="Text or a regular expression (git grep -E)")
    path: str = Field(default="", max_length=300, description="Optional folder or file to search in")


class RepoReadArgs(BaseModel):
    path: str = Field(min_length=1, max_length=300, description="A file, relative to the repository root")
    start: int = Field(default=1, ge=1, description="First line")
    lines: int = Field(default=200, ge=1, le=1000)


class BeginArgs(BaseModel):
    title: str = Field(min_length=3, max_length=200, description="What the fix is, in a few words")
    issue_id: str | None = Field(default=None, description="The issue it fixes, from forge.issues")


class WriteArgs(BaseModel):
    path: str = Field(min_length=1, max_length=300, description="A file, relative to the repository root")
    content: str = Field(max_length=400_000, description="The whole new content of the file")


class CheckArgs(BaseModel):
    repro_test: str = Field(
        min_length=3, max_length=300, description="The test you wrote first, e.g. tests/test_x.py::test_name"
    )


class ProposeArgs(BaseModel):
    root_cause: str = Field(min_length=10, max_length=4000, description="Why it broke, in plain English")
    risk: Literal["low", "medium", "high"] = Field(description="Your estimate; Sentinel may raise it")
    rollback_plan: str = Field(
        default="Roll back to the previous release from the System panel; the change is one revert commit.",
        max_length=2000,
    )


def forge_tools(ctx: "CoreContext") -> list[Tool]:
    def forge() -> Forge:
        if ctx.forge is None:
            raise ForgeError("Forge isn't running")
        return ctx.forge

    def current(tc: ToolContext) -> ForgeProposal:
        proposal = forge().proposal_for_task(tc.task_id)
        if proposal is None:
            raise ForgeError("Open a worktree first with forge.begin")
        return proposal

    async def issues(args: BaseModel, _tc: ToolContext) -> ToolResult:
        assert isinstance(args, IssuesArgs)
        found = await asyncio.to_thread(lambda: (forge().sync_issues(), forge().issues("open", args.limit))[1])
        rows = [{"id": i.id, "title": i.title, "source": i.source, "count": i.count, "score": i.score} for i in found]
        return ToolResult(json.dumps(rows, ensure_ascii=False) if rows else "No open issues.", untrusted=True)

    async def issue(args: BaseModel, _tc: ToolContext) -> ToolResult:
        assert isinstance(args, IssueArgs)
        i = forge().issue(args.issue_id)
        return ToolResult(f"# {i.title}\nsource: {i.source} · seen {i.count}×\n\n{i.detail}", untrusted=True)

    def tree_for(tc: ToolContext) -> Path:
        proposal = forge().proposal_for_task(tc.task_id)
        return forge().worktree(proposal.id).path if proposal else forge().require_repo()

    async def repo_search(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, RepoSearchArgs)
        root = tree_for(tc)
        command = ["grep", "-n", "-I", "-E", "--max-count=20", args.pattern, "--"]
        if args.path:
            command.append(args.path)
        try:
            out = await asyncio.to_thread(git, root, *command)
        except ForgeError:
            return ToolResult(f"No matches for '{args.pattern}'.")
        lines = out.splitlines()
        more = f"\n… {len(lines) - 80} more" if len(lines) > 80 else ""
        return ToolResult("\n".join(lines[:80]) + more)

    async def repo_read(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, RepoReadArgs)
        root = tree_for(tc)
        target = (root / args.path).resolve()
        if root.resolve() not in target.parents or ".git" in target.relative_to(root.resolve()).parts:
            raise ForgeError(f"'{args.path}' is outside the repository")
        if not target.is_file():
            raise ForgeError(f"No file '{args.path}'")
        text = target.read_text(encoding="utf-8", errors="replace").splitlines()
        chunk = text[args.start - 1 : args.start - 1 + args.lines]
        numbered = "\n".join(f"{n:5} {line}" for n, line in enumerate(chunk, start=args.start))
        tail = f"\n… ({len(text)} lines in all)" if args.start - 1 + args.lines < len(text) else ""
        return ToolResult(f"{args.path}\n{numbered}{tail}")

    async def begin(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, BeginArgs)
        existing = forge().proposal_for_task(tc.task_id)
        if existing is not None:
            return ToolResult(f"Already working in {existing.branch}.")
        proposal, tree = await asyncio.to_thread(
            forge().start_proposal, title=args.title, issue_id=args.issue_id, task_id=tc.task_id
        )
        ctx.audit.append(actor=tc.actor, action="forge.worktree", target_type="proposal", target_id=proposal.id,
                         details={"branch": proposal.branch, "base": proposal.base_commit})  # fmt: skip
        return ToolResult(
            f"Worktree ready on {proposal.branch} (base {proposal.base_commit[:10]}). Write the failing test first, "
            "then the fix, then run forge.check.",
            data={"proposal_id": proposal.id, "path": str(tree.path)},
        )

    async def write(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, WriteArgs)
        tree = forge().worktree(current(tc).id)
        rel = await asyncio.to_thread(tree.write, args.path, args.content)
        return ToolResult(f"Wrote {rel} ({len(args.content)} characters).")

    async def check(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, CheckArgs)
        proposal = current(tc)
        f = forge()
        tree = f.worktree(proposal.id)
        f.update(proposal.id, status="verifying", repro_test=args.repro_test)

        def verify() -> Report:
            head = tree.commit(f"Forge: {proposal.title}")
            verifier = Verifier(f.require_repo())
            report = Report()
            report.repro = verifier.repro(f.base_checkout(proposal.base_commit), tree.path, args.repro_test)
            changed = [c.path for c in tree.changes()]
            if report.repro.get("fails_on_base") and report.repro.get("passes_on_head"):
                report.checks = verifier.checks(tree.path, changed)
            f.update(proposal.id, head_commit=head, verification=report.to_json(), status="draft")
            return report

        report = await asyncio.to_thread(verify)
        verdict = "Everything passed." if report.passed else "Not yet: fix what failed and run forge.check again."
        return ToolResult(f"{verdict}\n{report.summary()}", data={"passed": report.passed})

    async def propose(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, ProposeArgs)
        proposal = current(tc)
        f = forge()
        tree = f.worktree(proposal.id)
        if not proposal.verification.get("passed"):
            raise ForgeError("Run forge.check until everything passes before proposing")
        head = await asyncio.to_thread(tree.commit, f"Forge: {proposal.title}")
        if head != proposal.head_commit:
            raise ForgeError("The worktree changed since the last forge.check: run it again")
        diff = await asyncio.to_thread(tree.diff)
        files = await asyncio.to_thread(tree.changes)
        protected = f.protected()
        touches = any(protected.matches(x.path) for x in files)
        risk = args.risk
        sentinel = load_sentinel()
        if sentinel is None:
            sentinel_review = {"available": False, "reason": NO_SENTINEL}
        else:
            sentinel_review = sentinel.review(
                diff=diff, files=[x.model_dump() for x in files], protected_patterns=protected.patterns
            )
            if RISK_ORDER.get(sentinel_review.get("risk", "low"), 0) > RISK_ORDER[risk]:
                risk = sentinel_review["risk"]
        critic = await ctx.engine.review(
            tc, "critic", f"Review this patch for correctness and code quality. Reply OK or list the problems.\n\n"
            f"Root cause given: {args.root_cause}\n\n```diff\n{diff[:30_000]}\n```",
        ) if ctx.engine is not None else None  # fmt: skip
        reviews = {
            "critic": {"output": critic.output if critic else None, "task_id": critic.id if critic else None},
            "sentinel": sentinel_review,
        }
        blocked = touches or sentinel_review.get("verdict") == "block"
        updated = f.update(
            proposal.id,
            root_cause=args.root_cause,
            diff=diff,
            diff_sha=diff_sha(diff),
            files=[x.model_dump() for x in files],
            reviews=reviews,
            risk=risk,
            rollback_plan=args.rollback_plan,
            touches_protected=touches,
            status="failed" if blocked else "ready",
        )
        if proposal.issue_id:
            f.set_issue_status(proposal.issue_id, "open" if blocked else "proposed", proposal.id)
        ctx.audit.append(actor=tc.actor, action="forge.proposed", target_type="proposal", target_id=proposal.id,
                         details={"diff_sha": updated.diff_sha, "risk": risk, "status": updated.status})  # fmt: skip
        ctx.bus.publish(
            "forge.proposal.created",
            {"proposal_id": proposal.id, "title": proposal.title, "risk": risk, "status": updated.status},
            actor=tc.actor,
        )
        if blocked:
            why = "it touches protected core" if touches else "Sentinel blocked it"
            return ToolResult(f"Proposal {proposal.id} can't go to the owner: {why}. {sentinel_review}")
        return ToolResult(
            f"Proposal {proposal.id} is ready for the owner: {len(files)} file(s), risk {risk}. "
            "They review it in the approvals tray; you can't apply it yourself."
        )

    return [
        Tool("forge.issues", "List open issues (errors, failed jobs, reports), ranked.", IssuesArgs, "read", issues),
        Tool("forge.issue", "One issue's details: messages, stack traces, reports.", IssueArgs, "read", issue),
        Tool("repo.search", "Search the codebase (git grep -E).", RepoSearchArgs, "read", repo_search),
        Tool("repo.read", "Read part of a file in the codebase, with line numbers.", RepoReadArgs, "read", repo_read),
        Tool(
            "forge.begin",
            "Open a worktree for a fix (one per task), branched from the current code.",
            BeginArgs,
            "write",
            begin,
            timeout_s=120,
        ),
        Tool(
            "forge.write",
            "Write a whole file in your worktree. Protected core and .git are refused.",
            WriteArgs,
            "write",
            write,
        ),
        Tool(
            "forge.check",
            "Commit the worktree and verify: the repro test must fail on the old code and pass on yours; then "
            "lint, types and the full test suite.",
            CheckArgs,
            "write",
            check,
            timeout_s=3600,
        ),
        Tool(
            "forge.propose",
            "Send the verified fix to the owner with its root cause, risk and rollback plan.",
            ProposeArgs,
            "write",
            propose,
            timeout_s=600,
        ),
    ]
