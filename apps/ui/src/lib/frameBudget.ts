// Watches frame times and turns on "smooth mode" (no backdrop blur, 1× pixel ratio) on a machine that can't
// keep up, instead of leaving the HUD janky. Pure decision logic is exported for tests.
import { useEffect } from 'react';
import { useUniverse } from '../state/store';

const WINDOW = 90; // frames per sample (~1.5 s at 60 fps)
const SLOW_MEDIAN_MS = 24; // below ~40 fps
const SLOW_WINDOWS = 2; // in a row, so a single hiccup (a big import, GC) doesn't trigger it
const IGNORE_GAP_MS = 250; // the window was hidden or the machine slept: not a slow frame

export function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
}

/** Feed one sample window; returns the new count of slow windows in a row. */
export function nextSlowStreak(streak: number, gaps: number[]): number {
  const usable = gaps.filter((g) => g < IGNORE_GAP_MS);
  if (usable.length < WINDOW / 2) return streak; // mostly hidden: no verdict
  return median(usable) > SLOW_MEDIAN_MS ? streak + 1 : 0;
}

export function shouldGoSmooth(streak: number): boolean {
  return streak >= SLOW_WINDOWS;
}

export function useFrameBudget(): void {
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    let gaps: number[] = [];
    let streak = 0;
    const tick = (now: number) => {
      gaps.push(now - last);
      last = now;
      if (gaps.length >= WINDOW) {
        streak = nextSlowStreak(streak, gaps);
        gaps = [];
        if (shouldGoSmooth(streak)) {
          const s = useUniverse.getState();
          streak = 0;
          if (!s.smooth) s.setSmooth(true);
          // In the universe, step the quality preset down too (Auto only); keep watching after each step.
          if (s.view === 'universe' && s.qualitySetting === 'auto' && s.quality !== 'lite')
            s.degradeQuality();
          else if (s.smooth) return; // nothing more to give up: stop sampling
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
}
