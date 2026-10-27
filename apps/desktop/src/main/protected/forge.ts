// Forge releases in Electron main (SPEC §9, ARCHITECTURE §7.2, ADR-0014). Protected core.
//
// The only way a Forge change gets applied: you click Approve on a card, this code fetches the proposal from
// Core, refuses anything that isn't ready (verified, reviewed by Sentinel, not touching protected core), and
// shows a native dialog with what it changes and its hash. Renderer code can't click a native dialog, and
// neither Core nor the renderer holds the supervisor token. Only after you confirm does the supervisor apply,
// redoing every check itself. Rollback asks the same way.
//
// The supervisor restarts Core after every apply and rollback (and rolls back on its own if a change breaks
// Core), so Core is often down right when there's something to record. Each time Core comes back healthy, this
// brings Core's record in line with the supervisor's releases (`sync`).
import type { ForgeDecision, ReleaseInfo, ReleasesState } from '@universe/shared-types';
import type { SupervisorRelease } from './supervisor';

export interface ProposalForApproval {
  id: string;
  title: string;
  root_cause: string;
  status: string;
  branch: string;
  base_commit: string;
  head_commit: string | null;
  diff_sha: string | null;
  risk: string | null;
  touches_protected: boolean;
  files: { path: string; status: string }[];
  verification: { passed?: boolean };
  reviews: { sentinel?: { available?: boolean; verdict?: string; findings?: { detail: string }[] } };
}

export interface ForgeDeps {
  core<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T>;
  applyRelease(
    body: Record<string, string>,
  ): Promise<{ ok: boolean; error?: string; release?: SupervisorRelease }>;
  rollbackRelease(tag: string): Promise<{ ok: boolean; error?: string; release?: SupervisorRelease }>;
  listReleases(): Promise<{ available: boolean; releases: SupervisorRelease[] }>;
  /** A native OS dialog; resolves true only when you press the confirm button. */
  confirm(opts: { title: string; message: string; detail: string; confirmLabel: string }): Promise<boolean>;
  log(event: string, fields?: Record<string, unknown>): void;
}

/** Why a proposal can't be approved yet, or null when it can. */
export function notApprovable(p: ProposalForApproval): string | null {
  if (p.status !== 'ready') return `It is ${p.status.replace('_', ' ')}, not ready.`;
  if (!p.verification.passed) return 'Its verification did not pass.';
  if (p.touches_protected) return 'It changes protected core, which only you can apply by hand.';
  const sentinel = p.reviews.sentinel;
  if (!sentinel?.available) return 'Sentinel has not reviewed it (install the Phase 5 protected-core patch).';
  if (sentinel.verdict !== 'pass') return 'Sentinel blocked it.';
  if (!p.head_commit || !p.diff_sha) return 'It has no verified commit.';
  return null;
}

export function approvalDetail(p: ProposalForApproval): string {
  const files = p.files.slice(0, 12).map((f) => `  ${f.status} ${f.path}`);
  if (p.files.length > 12) files.push(`  … and ${p.files.length - 12} more`);
  const findings = (p.reviews.sentinel?.findings ?? []).slice(0, 5).map((f) => `  • ${f.detail}`);
  return [
    `Why it broke: ${p.root_cause.slice(0, 400)}`,
    '',
    `Risk: ${p.risk ?? 'unknown'}`,
    'Files:',
    ...files,
    ...(findings.length ? ['Sentinel notes:', ...findings] : []),
    '',
    `Change id: ${p.diff_sha?.slice(0, 12)} · commit ${p.head_commit?.slice(0, 10)}`,
    'UNIVERSE restarts its backend, watches it for 30 minutes and rolls back on its own if it breaks.',
  ].join('\n');
}

/** How many of the latest releases `sync` looks at. */
export const SYNC_RELEASES = 20;

interface ProposalState {
  status: string;
}

export class ForgeControl {
  private syncedPid: number | null = null;
  private pending = false;
  private syncing: Promise<number> | null = null;

  constructor(private readonly deps: ForgeDeps) {}

  /** Call with Core's state from every supervisor status: syncs once per Core process, and retries what failed. */
  coreState(core: { state: string; pid: number | null } | undefined): void {
    if (core?.state !== 'healthy' || core.pid === null || this.syncing) return;
    if (core.pid === this.syncedPid && !this.pending) return;
    const pid = core.pid;
    this.syncing = this.sync()
      .then((recorded) => {
        this.syncedPid = pid;
        this.pending = false;
        if (recorded) this.deps.log('forge_synced', { recorded });
        return recorded;
      })
      .catch((err: unknown) => {
        this.pending = true;
        this.deps.log('forge_sync_failed', { error: String(err) });
        return 0;
      })
      .finally(() => {
        this.syncing = null;
      });
  }

  /**
   * Record in Core what the supervisor did and Core missed. Core still checks an "applied" claim against git.
   * Throws when Core or the supervisor can't be reached (try again later); returns how many records it made.
   */
  async sync(): Promise<number> {
    const { available, releases } = await this.deps.listReleases();
    if (!available) return 0;
    let recorded = 0;
    for (const r of releases.slice(-SYNC_RELEASES)) {
      if (!r.proposal_id) continue;
      const path = `/forge/proposals/${encodeURIComponent(r.proposal_id)}`;
      const p = await this.deps.core<ProposalState>('GET', path);
      let status = p.status;
      if (status === 'ready' || status === 'approved') {
        await this.deps.core('POST', `${path}/release`, { event: 'applied', release: r.tag });
        status = 'applied';
        recorded += 1;
      }
      if (r.status === 'rolled_back' && status === 'applied') {
        await this.deps.core('POST', `${path}/release`, { event: 'rolled_back', release: r.tag });
        recorded += 1;
      }
    }
    return recorded;
  }

  private record(proposalId: string, event: 'applied' | 'rolled_back', tag: string): Promise<void> {
    return this.deps
      .core<unknown>('POST', `/forge/proposals/${encodeURIComponent(proposalId)}/release`, {
        event,
        release: tag,
      })
      .then(() => undefined)
      .catch((err: unknown) => {
        this.pending = true; // Core is likely restarting: the next healthy status syncs it
        this.deps.log('forge_record_failed', { proposal: proposalId, event, error: String(err) });
      });
  }

  async approve(proposalId: string): Promise<ForgeDecision> {
    const p = await this.deps.core<ProposalForApproval>(
      'GET',
      `/forge/proposals/${encodeURIComponent(proposalId)}`,
    );
    const blocked = notApprovable(p);
    if (blocked) return { ok: false, message: blocked };
    const yes = await this.deps.confirm({
      title: 'Apply a Forge change',
      message: `Apply “${p.title}”?`,
      detail: approvalDetail(p),
      confirmLabel: 'Apply',
    });
    if (!yes) return { ok: false, message: 'You cancelled. Nothing changed.' };
    this.deps.log('forge_approved', { proposal: p.id, diff_sha: p.diff_sha });
    const result = await this.deps.applyRelease({
      proposal_id: p.id,
      branch: p.branch,
      base_commit: p.base_commit,
      head_commit: p.head_commit!,
      diff_sha: p.diff_sha!,
      title: p.title,
    });
    if (!result.ok || !result.release)
      return { ok: false, message: result.error ?? 'The supervisor refused it.' };
    const tag = result.release.tag;
    await this.record(p.id, 'applied', tag);
    return { ok: true, message: `Applied as ${tag}. Watching it for 30 minutes.`, release: tag };
  }

  async rollback(tag: string): Promise<ForgeDecision> {
    const { releases } = await this.deps.listReleases();
    const release = releases.find((r) => r.tag === tag);
    if (!release) return { ok: false, message: `No release ${tag}.` };
    if (release.status === 'rolled_back') return { ok: false, message: `${tag} is already rolled back.` };
    const yes = await this.deps.confirm({
      title: 'Roll back a change',
      message: `Roll back “${release.title}” (${tag})?`,
      detail:
        'The change is undone with a revert commit; anything committed since stays. The backend restarts.',
      confirmLabel: 'Roll back',
    });
    if (!yes) return { ok: false, message: 'You cancelled. Nothing changed.' };
    const result = await this.deps.rollbackRelease(tag);
    if (!result.ok) return { ok: false, message: result.error ?? 'The supervisor refused it.' };
    if (release.proposal_id) await this.record(release.proposal_id, 'rolled_back', tag);
    return { ok: true, message: `Rolled back ${tag}.`, release: tag };
  }

  async releases(): Promise<ReleasesState> {
    const state = await this.deps.listReleases();
    const releases: ReleaseInfo[] = state.releases.map((r) => ({
      tag: r.tag,
      commit: r.commit,
      created_at: new Date(r.created_at * 1000).toISOString(),
      proposal_id: r.proposal_id,
      title: r.title,
      status: r.status,
      current: r.current,
    }));
    return { available: state.available, releases: releases.reverse() };
  }
}
