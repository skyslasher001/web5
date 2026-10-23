import { describe, expect, it } from 'vitest';
import {
  currentSample,
  median,
  perfActive,
  pushWindow,
  reportRender,
  setPerfActive,
  subscribePerf,
  summarize,
} from './perf';

const frames = (ms: number, n = 30) => Array.from({ length: n }, () => ms);

describe('perf readout', () => {
  it('summarises a window into fps, median frame time and the worst frame', () => {
    const s = summarize(frames(16.7));
    expect(s.fps).toBe(60); // 1000 / 16.7 ≈ 59.9 → 60
    expect(s.frameMs).toBe(16.7);
    expect(s.worstMs).toBe(16.7);
  });

  it('drops hidden-window gaps so a backgrounded tab does not read as 0 fps', () => {
    const s = summarize([...frames(16.7, 28), 5000, 9000]); // two huge gaps (tab was hidden)
    expect(s.fps).toBe(60);
    expect(s.worstMs).toBeLessThan(250); // the 5 s / 9 s gaps are ignored
  });

  it('reports a worst frame distinct from the median', () => {
    const s = summarize([...frames(16.7, 29), 40]); // one 40 ms hitch
    expect(s.frameMs).toBe(16.7);
    expect(s.worstMs).toBe(40);
  });

  it('is empty when there is nothing usable to measure', () => {
    expect(summarize([])).toEqual({ fps: 0, frameMs: 0, worstMs: 0 });
    expect(summarize([5000, 9000])).toEqual({ fps: 0, frameMs: 0, worstMs: 0 });
    expect(median([3, 1, 2])).toBe(2);
  });

  it('publishes a window with the latest render counts to subscribers', () => {
    let seen = 0;
    const off = subscribePerf(() => (seen += 1));
    reportRender(42, 50000);
    pushWindow(frames(16.7));
    expect(seen).toBe(1);
    expect(currentSample()).toMatchObject({ fps: 60, calls: 42, points: 50000 });
    off();
    pushWindow(frames(16.7));
    expect(seen).toBe(1); // unsubscribed: no further notifications
  });

  it('clears to zero when the sampler stops, so a stale reading never lingers', () => {
    setPerfActive(true);
    expect(perfActive()).toBe(true);
    reportRender(10, 10);
    pushWindow(frames(16.7));
    expect(currentSample().calls).toBe(10);
    setPerfActive(false);
    expect(perfActive()).toBe(false);
    expect(currentSample()).toEqual({ fps: 0, frameMs: 0, worstMs: 0, calls: 0, points: 0 });
  });
});
