// Perf HUD (IDEAS S5): a small, always-on-top readout of frame rate, frame time and the renderer's draw
// calls, toggled in System → Display and off by default. It serves the "well running" goal and the pending
// `pnpm bench:universe` tuning on the owner's GPU. Purely additive: it never changes what the universe draws.
import { tokens } from '@universe/design-tokens';
import { useEffect, useSyncExternalStore } from 'react';
import { currentSample, pushWindow, setPerfActive, subscribePerf } from '../lib/perf';
import { useUniverse } from '../state/store';
import { QUALITY_LABEL } from '../universe/quality';

const WINDOW = 30; // frames per reading (~0.5 s at 60 fps): responsive without being noisy.

/** Samples frame times while the HUD is on, publishing a reading every WINDOW frames. */
function usePerfSampler(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    setPerfActive(true);
    let raf = 0;
    let last = performance.now();
    let gaps: number[] = [];
    const tick = (now: number) => {
      gaps.push(now - last);
      last = now;
      if (gaps.length >= WINDOW) {
        pushWindow(gaps);
        gaps = [];
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      setPerfActive(false);
    };
  }, [enabled]);
}

function fpsColor(fps: number): string {
  if (fps >= 55) return tokens.color.green;
  if (fps >= 30) return tokens.color.amber;
  return tokens.color.danger;
}

export function PerfHud() {
  const enabled = useUniverse((s) => s.perfHud);
  const quality = useUniverse((s) => s.quality);
  const smooth = useUniverse((s) => s.smooth);
  usePerfSampler(enabled);
  const sample = useSyncExternalStore(subscribePerf, currentSample, currentSample);
  if (!enabled) return null;
  return (
    <div
      className="pointer-events-none absolute left-4 top-16 rounded-md border border-hairline-1 bg-space-0/85 px-2.5 py-2 font-mono text-[11px] leading-tight text-ink-2 shadow-lg backdrop-blur"
      data-testid="perf-hud"
      aria-hidden
    >
      <div className="flex items-baseline gap-2">
        <span style={{ color: fpsColor(sample.fps) }} className="text-sm font-semibold tabular-nums">
          {sample.fps} fps
        </span>
        <span className="tabular-nums text-ink-3">
          {sample.frameMs.toFixed(1)} ms · worst {sample.worstMs.toFixed(1)}
        </span>
      </div>
      <div className="mt-1 tabular-nums text-ink-3">
        {sample.calls} draw calls · {sample.points.toLocaleString()} pts
      </div>
      <div className="mt-0.5 text-ink-3">
        {quality ? QUALITY_LABEL[quality] : '—'}
        {smooth ? ' · smooth' : ''}
      </div>
    </div>
  );
}
