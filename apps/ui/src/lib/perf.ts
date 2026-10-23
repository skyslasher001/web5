// A live performance readout for the Perf HUD overlay (IDEAS S5): frame rate, frame time and the renderer's
// draw calls, sampled only while the overlay is on so it costs nothing when off. The sampler and the renderer
// write into one small observable; the overlay subscribes and repaints a few times a second, not per frame.
// Pure summarising logic is exported for tests.

export interface PerfSample {
  /** Frames per second from the median frame time in the last window. */
  fps: number;
  /** Median frame time in the window, ms. */
  frameMs: number;
  /** Worst (longest) usable frame in the window, ms — the hitch you feel. */
  worstMs: number;
  /** Draw calls and points the renderer last reported (0 until the 3D scene reports). */
  calls: number;
  points: number;
}

const EMPTY: PerfSample = { fps: 0, frameMs: 0, worstMs: 0, calls: 0, points: 0 };
// A gap longer than this is a tab-sleep or stall, not a frame — drop it. Kept high (not frameBudget's 250 ms)
// because a genuinely slow render (a few hundred ms on weak hardware) is exactly what the HUD should show.
const IGNORE_GAP_MS = 2000;

let sample: PerfSample = EMPTY;
let render = { calls: 0, points: 0 };
let active = false;
const listeners = new Set<() => void>();

/** The overlay reads this; it's a stable reference between windows so useSyncExternalStore won't loop. */
export function currentSample(): PerfSample {
  return sample;
}

export function subscribePerf(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** The renderer reports its draw-call counts each frame while the HUD is on; cheap, so no throttling here. */
export function reportRender(calls: number, points: number): void {
  render = { calls, points };
}

/** Whether the HUD sampler is running — the renderer probe checks this before reading GPU info. */
export function perfActive(): boolean {
  return active;
}

export function setPerfActive(on: boolean): void {
  active = on;
  if (!on) {
    sample = EMPTY;
    render = { calls: 0, points: 0 };
  }
}

export function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
}

/** Turn one window of frame gaps into a reading. Big gaps (tab hidden) are dropped so they don't skew it. */
export function summarize(gaps: number[]): Pick<PerfSample, 'fps' | 'frameMs' | 'worstMs'> {
  const usable = gaps.filter((g) => g > 0 && g < IGNORE_GAP_MS);
  if (usable.length === 0) return { fps: 0, frameMs: 0, worstMs: 0 };
  const frameMs = median(usable);
  return {
    fps: frameMs > 0 ? Math.round(1000 / frameMs) : 0,
    frameMs: Math.round(frameMs * 10) / 10,
    worstMs: Math.round(Math.max(...usable) * 10) / 10,
  };
}

/** Publish a window's reading (plus the latest render counts) to the overlay. */
export function pushWindow(gaps: number[]): void {
  sample = { ...summarize(gaps), ...render };
  for (const fn of listeners) fn();
}
