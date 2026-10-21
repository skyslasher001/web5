"""REST for Forge (SPEC §9, ADR-0014): status, issues, your bug reports, starting a fix, proposals, rejecting.

There is no approve or apply endpoint, on purpose: approval is a native dialog in Electron main and the
supervisor applies (protected core). Core only records what happened, and checks a claimed release against git.
"""

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from universe_common.schema import ApiModel
from universe_common.timeutil import utcnow
from universe_core.context import CoreContext
from universe_core.forge import DAILY_CAP, Forge, ForgeError, ForgeIssue, ForgeProposal, git
from universe_core.forge_tools import NO_SENTINEL, load_sentinel

router = APIRouter(prefix="/api/v1")


def get_ctx(request: Request) -> CoreContext:
    return request.app.state.ctx


Ctx = Annotated[CoreContext, Depends(get_ctx)]

NO_FORGE_AGENT = (
    "The Forge agent isn't installed yet: agents/forge.yaml is protected core "
    "(docs/proposals/phase-5-protected-core.md)."
)


class ForgeStatus(ApiModel):
    available: bool
    reason: str | None
    agent: bool
    agent_reason: str | None
    sentinel: bool
    sentinel_reason: str | None
    proposals_today: int
    daily_cap: int
    repo: str | None
    head: str | None


class ReportRequest(BaseModel):
    text: str = Field(min_length=5, max_length=4000)


class FixResponse(ApiModel):
    task_id: str


class ReleaseEvent(BaseModel):
    event: Literal["applied", "rolled_back"]
    release: str = Field(min_length=1, max_length=120)


def _forge(ctx: CoreContext) -> Forge:
    if ctx.forge is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Forge isn't running")
    return ctx.forge


def _status(ctx: CoreContext) -> ForgeStatus:
    f = _forge(ctx)
    reason = f.unavailable_reason
    head = None
    if reason is None:
        try:
            head = git(f.require_repo(), "rev-parse", "HEAD").strip()
        except ForgeError as exc:
            reason = str(exc)
    has_agent = "forge" in ctx.agents
    has_sentinel = load_sentinel() is not None
    return ForgeStatus(
        available=reason is None,
        reason=reason,
        agent=has_agent,
        agent_reason=None if has_agent else NO_FORGE_AGENT,
        sentinel=has_sentinel,
        sentinel_reason=None if has_sentinel else NO_SENTINEL,
        proposals_today=f.proposals_today(),
        daily_cap=DAILY_CAP,
        repo=str(f.repo) if f.repo else None,
        head=head,
    )


@router.get("/forge/status", response_model=ForgeStatus)
async def forge_status(ctx: Ctx) -> ForgeStatus:
    return await asyncio.to_thread(_status, ctx)


@router.get("/forge/issues", response_model=list[ForgeIssue])
async def forge_issues(ctx: Ctx, status_filter: str | None = None) -> list[ForgeIssue]:
    f = _forge(ctx)

    def work() -> list[ForgeIssue]:
        f.sync_issues()
        return f.issues(status_filter)

    return await asyncio.to_thread(work)


@router.post("/forge/reports", response_model=ForgeIssue, status_code=status.HTTP_201_CREATED)
async def forge_report(ctx: Ctx, body: ReportRequest) -> ForgeIssue:
    issue = await asyncio.to_thread(_forge(ctx).report, body.text)
    ctx.audit.append(actor="user", action="forge.report", target_type="issue", target_id=issue.id)
    ctx.bus.publish("forge.issue.triaged", {"issue_id": issue.id, "title": issue.title}, actor="user")
    return issue


@router.post("/forge/issues/{issue_id}/ignore", response_model=ForgeIssue)
async def ignore_issue(ctx: Ctx, issue_id: str) -> ForgeIssue:
    f = _forge(ctx)
    try:
        f.issue(issue_id)
        f.set_issue_status(issue_id, "ignored")
        return f.issue(issue_id)
    except ForgeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/forge/issues/{issue_id}/fix", response_model=FixResponse, status_code=status.HTTP_202_ACCEPTED)
async def fix_issue(ctx: Ctx, issue_id: str) -> FixResponse:
    f = _forge(ctx)
    if f.unavailable_reason:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f.unavailable_reason)
    if "forge" not in ctx.agents:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_FORGE_AGENT)
    if ctx.engine is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The agent engine is not running")
    try:
        issue = f.issue(issue_id)
    except ForgeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    instruction = (
        f"Fix issue {issue.id}: {issue.title}\n\nRead it with forge.issue, find the cause in the code, write a "
        "failing test first, then the smallest fix, run forge.check until everything passes, and propose it."
    )
    task_id = ctx.engine.start("forge", instruction)
    ctx.audit.append(actor="user", action="forge.fix_requested", target_type="issue", target_id=issue.id,
                     task_id=task_id)  # fmt: skip
    return FixResponse(task_id=task_id)


@router.get("/forge/proposals", response_model=list[ForgeProposal])
async def forge_proposals(ctx: Ctx, status_filter: str | None = None) -> list[ForgeProposal]:
    return await asyncio.to_thread(_forge(ctx).proposals, status_filter)


@router.get("/forge/proposals/{proposal_id}", response_model=ForgeProposal)
async def forge_proposal(ctx: Ctx, proposal_id: str) -> ForgeProposal:
    try:
        return await asyncio.to_thread(_forge(ctx).proposal, proposal_id)
    except ForgeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/forge/proposals/{proposal_id}/reject", response_model=ForgeProposal)
async def reject_proposal(ctx: Ctx, proposal_id: str) -> ForgeProposal:
    f = _forge(ctx)
    try:
        p = f.proposal(proposal_id)
    except ForgeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if p.status in ("applied", "rolled_back", "rejected"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"It's already {p.status.replace('_', ' ')}")
    if p.status == "verifying":  # the verify thread would set it back to draft, with its worktree gone
        raise HTTPException(status.HTTP_409_CONFLICT, "It's being verified: reject it when the checks finish")
    updated = f.update(proposal_id, status="rejected", decided_at=utcnow())
    if p.issue_id:
        f.set_issue_status(p.issue_id, "open")
    await asyncio.to_thread(f.discard_worktree, proposal_id)
    ctx.audit.append(actor="user", action="forge.rejected", target_type="proposal", target_id=proposal_id,
                     details={"diff_sha": p.diff_sha})  # fmt: skip
    return updated


@router.post("/forge/proposals/{proposal_id}/release", response_model=ForgeProposal)
async def record_release(ctx: Ctx, proposal_id: str, body: ReleaseEvent) -> ForgeProposal:
    """Electron main reports what the supervisor did. An 'applied' claim is checked against git."""
    f = _forge(ctx)
    try:
        p = f.proposal(proposal_id)
    except ForgeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if body.event == "applied":
        if p.status == "applied" and p.release == body.release:
            return p  # idempotent: Electron main re-syncs the same applied release after a Core restart
        if p.status in ("rejected", "failed", "rolled_back"):
            raise HTTPException(status.HTTP_409_CONFLICT, f"A {p.status.replace('_', ' ')} proposal can't be applied")
        if not p.head_commit:
            raise HTTPException(status.HTTP_409_CONFLICT, "The proposal has no verified commit")
        try:
            await asyncio.to_thread(git, f.require_repo(), "merge-base", "--is-ancestor", p.head_commit, "HEAD")
        except ForgeError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "That commit isn't in the codebase") from exc
        updated = f.update(proposal_id, status="applied", release=body.release, decided_at=utcnow())
        if p.issue_id:
            f.set_issue_status(p.issue_id, "fixed")
        ctx.bus.publish("forge.applied", {"proposal_id": proposal_id, "release": body.release}, actor="supervisor")
    else:
        if p.status != "applied":
            raise HTTPException(status.HTTP_409_CONFLICT, "Only an applied proposal can be rolled back")
        updated = f.update(proposal_id, status="rolled_back")
        if p.issue_id:
            f.set_issue_status(p.issue_id, "open")
        ctx.bus.publish("forge.rolled_back", {"proposal_id": proposal_id, "release": body.release}, actor="supervisor")
    ctx.audit.append(actor="supervisor", action=f"forge.{body.event}", target_type="proposal", target_id=proposal_id,
                     details={"release": body.release})  # fmt: skip
    return updated
