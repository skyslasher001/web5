import { describe, expect, it, vi } from 'vitest';
import { ForgeControl, notApprovable, type ForgeDeps, type ProposalForApproval } from './forge';

const READY: ProposalForApproval = {
  id: 'p1',
  title: 'Fix add',
  root_cause: 'add() subtracted',
  status: 'ready',
  branch: 'forge/p1',
  base_commit: 'b'.repeat(40),
  head_commit: 'h'.repeat(40),
  diff_sha: 'd'.repeat(64),
  risk: 'low',
  touches_protected: false,
  files: [{ path: 'calc/__init__.py', status: 'M' }],
  verification: { passed: true },
  reviews: { sentinel: { available: true, verdict: 'pass', findings: [] } },
};

function deps(over: Partial<ForgeDeps> = {}, proposal = READY) {
  const calls: string[] = [];
  const d: ForgeDeps = {
    core: vi.fn(async (method: string, path: string) => {
      calls.push(`${method} ${path}`);
      return proposal as never;
    }) as ForgeDeps['core'],
    applyRelease: vi.fn(async () => ({
      ok: true,
      release: {
        tag: 'universe/release-1', commit: READY.head_commit!, proposal_id: 'p1', title: 'Fix add',
        created_at: 1_800_000_000, status: 'watching' as const, current: true,
      },
    })), // prettier-ignore
    rollbackRelease: vi.fn(async () => ({ ok: true })),
    listReleases: vi.fn(async () => ({
      available: true,
      releases: [
        {
          tag: 'universe/release-1', commit: 'c', proposal_id: 'p1', title: 'Fix add',
          created_at: 1_800_000_000, status: 'good' as const, current: true,
        },
      ],
    })), // prettier-ignore
    confirm: vi.fn(async () => true),
    log: vi.fn(),
    ...over,
  };
  return { d, calls };
}

describe('Forge approval in Electron main', () => {
  it('applies only after the native dialog, then records the release in Core', async () => {
    const { d, calls } = deps();
    const result = await new ForgeControl(d).approve('p1');
    expect(result).toEqual(expect.objectContaining({ ok: true, release: 'universe/release-1' }));
    expect(d.confirm).toHaveBeenCalledOnce();
    expect(d.applyRelease).toHaveBeenCalledWith(
      expect.objectContaining({
        proposal_id: 'p1',
        head_commit: READY.head_commit,
        diff_sha: READY.diff_sha,
      }),
    );
    expect(calls).toContain('POST /forge/proposals/p1/release');
  });

  it('applies nothing when you cancel the dialog', async () => {
    const { d } = deps({ confirm: vi.fn(async () => false) });
    expect((await new ForgeControl(d).approve('p1')).ok).toBe(false);
    expect(d.applyRelease).not.toHaveBeenCalled();
  });

  it('never even asks for what is not ready', async () => {
    const cases: [Partial<ProposalForApproval>, string][] = [
      [{ status: 'failed' }, 'not ready'],
      [{ verification: { passed: false } }, 'verification'],
      [{ touches_protected: true }, 'protected core'],
      [{ reviews: { sentinel: { available: false } } }, 'Sentinel has not reviewed'],
      [{ reviews: { sentinel: { available: true, verdict: 'block' } } }, 'Sentinel blocked'],
      [{ diff_sha: null }, 'no verified commit'],
    ];
    for (const [change, why] of cases) {
      const proposal = { ...READY, ...change };
      expect(notApprovable(proposal)).toContain(why);
      const { d } = deps({}, proposal);
      const result = await new ForgeControl(d).approve('p1');
      expect(result.ok).toBe(false);
      expect(d.confirm).not.toHaveBeenCalled();
      expect(d.applyRelease).not.toHaveBeenCalled();
    }
  });

  it('reports a supervisor refusal as it is', async () => {
    const { d } = deps({
      applyRelease: vi.fn(async () => ({ ok: false, error: 'The branch moved after it was verified' })),
    });
    expect(await new ForgeControl(d).approve('p1')).toEqual({
      ok: false,
      message: 'The branch moved after it was verified',
    });
  });

  it('rolls back after the native dialog and tells Core', async () => {
    const { d, calls } = deps();
    const result = await new ForgeControl(d).rollback('universe/release-1');
    expect(result.ok).toBe(true);
    expect(d.rollbackRelease).toHaveBeenCalledWith('universe/release-1');
    expect(calls).toContain('POST /forge/proposals/p1/release');
    const cancelled = deps({ confirm: vi.fn(async () => false) });
    expect((await new ForgeControl(cancelled.d).rollback('universe/release-1')).ok).toBe(false);
    expect(cancelled.d.rollbackRelease).not.toHaveBeenCalled();
  });

  it('catches Core up when it was restarting as the release was recorded (regression)', async () => {
    // Core is down right after the supervisor applies: the record fails, then the next healthy status syncs it.
    let coreUp = false;
    let status = 'ready';
    const posts: unknown[] = [];
    const { d } = deps({
      core: vi.fn(async (method: string, _path: string, body?: unknown) => {
        if (method === 'POST') {
          if (!coreUp) throw new Error('net::ERR_CONNECTION_REFUSED');
          posts.push(body);
          status = 'applied';
          return {} as never;
        }
        return { ...READY, status } as never;
      }) as ForgeDeps['core'],
      listReleases: vi.fn(async () => ({
        available: true,
        releases: [
          {
            tag: 'universe/release-1', commit: 'c', proposal_id: 'p1', title: 'Fix add',
            created_at: 1_800_000_000, status: 'watching' as const, current: true,
          },
        ],
      })), // prettier-ignore
    });
    const forge = new ForgeControl(d);
    expect((await forge.approve('p1')).ok).toBe(true);
    expect(d.log).toHaveBeenCalledWith('forge_record_failed', expect.objectContaining({ event: 'applied' }));
    forge.coreState({ state: 'starting', pid: null });
    coreUp = true;
    forge.coreState({ state: 'healthy', pid: 42 });
    await vi.waitFor(() => expect(posts).toEqual([{ event: 'applied', release: 'universe/release-1' }]));
    // In step now: the same Core process doesn't sync again.
    await vi.waitFor(() => expect(d.log).toHaveBeenCalledWith('forge_synced', { recorded: 1 }));
    forge.coreState({ state: 'healthy', pid: 42 });
    expect(d.listReleases).toHaveBeenCalledTimes(1);
  });

  it('records a rollback the supervisor made on its own, and nothing when Core is already in step', async () => {
    const posts: unknown[] = [];
    const statuses: Record<string, string> = { p1: 'ready', p2: 'applied', p3: 'rolled_back' };
    const release = (tag: string, proposal_id: string, status: 'good' | 'rolled_back') => ({
      tag, commit: 'c', proposal_id, title: tag, created_at: 1_800_000_000, status, current: false,
    }); // prettier-ignore
    const { d } = deps({
      core: vi.fn(async (method: string, path: string, body?: unknown) => {
        if (method === 'POST') posts.push([path, body]);
        return { ...READY, status: statuses[path.split('/')[3]!] } as never;
      }) as ForgeDeps['core'],
      listReleases: vi.fn(async () => ({
        available: true,
        releases: [
          release('universe/release-1', 'p1', 'rolled_back'),
          release('universe/release-2', 'p2', 'good'),
          release('universe/release-3', 'p3', 'rolled_back'),
        ],
      })),
    });
    expect(await new ForgeControl(d).sync()).toBe(2);
    expect(posts).toEqual([
      ['/forge/proposals/p1/release', { event: 'applied', release: 'universe/release-1' }],
      ['/forge/proposals/p1/release', { event: 'rolled_back', release: 'universe/release-1' }],
    ]);
  });

  it('keeps retrying the sync while Core is unreachable', async () => {
    let up = false;
    const { d } = deps({
      core: vi.fn(async () => {
        if (!up) throw new Error('net::ERR_CONNECTION_REFUSED');
        return { ...READY, status: 'applied' } as never;
      }) as ForgeDeps['core'],
    });
    const forge = new ForgeControl(d);
    forge.coreState({ state: 'healthy', pid: 7 });
    await vi.waitFor(() => expect(d.log).toHaveBeenCalledWith('forge_sync_failed', expect.anything()));
    up = true;
    forge.coreState({ state: 'healthy', pid: 7 });
    await vi.waitFor(() => expect(d.listReleases).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(d.core).toHaveBeenCalledTimes(2));
  });
});
