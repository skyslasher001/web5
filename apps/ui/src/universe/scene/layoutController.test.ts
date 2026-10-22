// Regression tests for the layout controller (a fake Web Worker stands in for layout.worker.ts).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CoreApi } from '../../lib/api';
import type { LayoutRequest, LayoutResponse } from './layout.worker';
import { LayoutController, useLayout } from './layoutController';
import { buildScene, type SceneRow } from './sceneData';

const posted: LayoutRequest[] = [];
const workers: FakeWorker[] = [];

class FakeWorker {
  onmessage: ((e: MessageEvent<LayoutResponse>) => void) | null = null;
  onerror: ((e: ErrorEvent) => void) | null = null;
  constructor() {
    workers.push(this);
  }
  postMessage(request: LayoutRequest) {
    posted.push(request);
  }
  terminate() {}
  /** Finish the oldest request still waiting. */
  answer() {
    const r = posted.shift()!;
    const n = r.input.n;
    const result = {
      positions: new Float32Array(n * 3),
      galaxyCentres: new Float32Array(0),
      galaxyRadii: new Float32Array(0),
      extent: 100,
    };
    this.onmessage?.({ data: { id: r.id, kind: r.kind, result, ms: 1 } } as MessageEvent<LayoutResponse>);
  }
}

const row = (id: string): SceneRow => ({
  id,
  type: 'note',
  title: id,
  galaxy: null,
  created: 1_700_000_000,
  captured: 1_700_000_000,
  opened: 0,
  opens: 0,
  status: 'active',
  ideaStage: null,
  pinned: false,
});
const sceneOf = (n: number) =>
  buildScene(
    Array.from({ length: n }, (_, i) => row(`i${i}`)),
    { sources: [], targets: [], states: [] },
    [],
  );
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  posted.length = 0;
  vi.stubGlobal('Worker', FakeWorker);
  useLayout.setState({ current: null, computing: null, notice: null });
});
afterEach(() => vi.unstubAllGlobals());

describe('layout controller', () => {
  it('computes only the newest layout while one is running (no growing queue during an import)', async () => {
    const c = new LayoutController({} as CoreApi);
    void c.show('graph', sceneOf(3), 1);
    void c.show('graph', sceneOf(4), 2);
    void c.show('graph', sceneOf(5), 3);
    await flush();
    expect(posted).toHaveLength(1); // version 1 is running; 2 was superseded by 3 while it waited
    workers.at(-1)!.answer();
    await flush();
    expect(posted).toHaveLength(1);
    expect(posted[0]!.input.n).toBe(5);
    workers.at(-1)!.answer();
    await flush();
    expect(useLayout.getState().current?.sceneVersion).toBe(3);
    c.dispose();
  });

  it('replaces what was drawn with an empty layout when the last item goes', async () => {
    const c = new LayoutController({} as CoreApi);
    void c.show('project', sceneOf(2), 1);
    await flush();
    workers.at(-1)!.answer();
    await flush();
    await c.show('project', sceneOf(0), 2);
    const current = useLayout.getState().current;
    expect(current).not.toBeNull();
    expect(current!.positions).toHaveLength(0);
    expect(current!.sceneVersion).toBe(2);
    c.dispose();
  });

  it('keeps the same fallback object while Semantic computes, so nothing rebuilds every poll', async () => {
    vi.useFakeTimers();
    const api = {
      semanticLayout: async () => ({
        status: 'computing',
        reason: 'Arranging…',
        stale: false,
        ids: [],
        positions: [],
      }),
    } as unknown as CoreApi;
    const c = new LayoutController(api);
    const scene = sceneOf(3);
    const first = c.show('semantic', scene, 1);
    await vi.advanceTimersByTimeAsync(0);
    workers.at(-1)!.answer();
    await first;
    const shown = useLayout.getState().current;
    expect(shown?.kind).toBe('project');
    await vi.advanceTimersByTimeAsync(3100); // the next poll
    expect(useLayout.getState().current).toBe(shown);
    c.dispose();
    vi.useRealTimers();
  });

  it('settles a computation cut short by dispose, so the next layout still computes', async () => {
    const c = new LayoutController({} as CoreApi);
    void c.show('graph', sceneOf(3), 1);
    await flush();
    expect(useLayout.getState().computing).toBe('graph');
    c.dispose(); // React StrictMode (or leaving the view) while the worker computes
    await flush();
    expect(useLayout.getState().computing).toBeNull(); // no "Arranging…" left behind
    posted.length = 0;
    void c.show('graph', sceneOf(4), 2);
    await flush();
    expect(posted).toHaveLength(1);
    workers.at(-1)!.answer();
    await flush();
    expect(useLayout.getState().current?.sceneVersion).toBe(2);
    expect(useLayout.getState().computing).toBeNull();
    c.dispose();
  });

  it('says so when the worker fails, and computes again on the next request', async () => {
    const c = new LayoutController({} as CoreApi);
    void c.show('graph', sceneOf(3), 1);
    await flush();
    workers.at(-1)!.onerror?.({ message: 'out of memory' } as ErrorEvent);
    await flush();
    expect(useLayout.getState().computing).toBeNull();
    expect(useLayout.getState().notice).toContain('out of memory');
    posted.length = 0;
    void c.show('graph', sceneOf(4), 2);
    await flush();
    expect(posted).toHaveLength(1);
    workers.at(-1)!.answer();
    await flush();
    expect(useLayout.getState().current?.sceneVersion).toBe(2);
    c.dispose();
  });
});
