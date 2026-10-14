// Shared, non-React state for the scene: the GPU picker, what's under the pointer, and the search
// constellation (result indices, in result order).
import { create } from 'zustand';

interface Interaction {
  hovered: number; // item index under the pointer, -1 none
  /** Search results shown as a constellation: item indices in rank order. */
  results: number[];
  /** The query those results answer (while typing, the previous query's results stay on screen). */
  resultsFor: string;
  /** Enter was pressed before the results for this query arrived: fly to its best match when they do. */
  pendingFly: string | null;
  setHovered(index: number): void;
  setResults(results: number[], query?: string): void;
  setPendingFly(query: string | null): void;
}

export const useInteraction = create<Interaction>()((set) => ({
  hovered: -1,
  results: [],
  resultsFor: '',
  pendingFly: null,
  setHovered: (hovered) => set((s) => (s.hovered === hovered ? s : { hovered })),
  setResults: (results, query = '') => set({ results, resultsFor: query }),
  setPendingFly: (pendingFly) => set({ pendingFly }),
}));

/** The result Enter should fly to: the best match, but only if the results answer what's typed now. */
export function enterTarget(s: { results: number[]; resultsFor: string }, typed: string): number | null {
  return s.resultsFor === typed.trim() && s.results.length ? s.results[0]! : null;
}

/** Set by ItemPoints once the GPU picking pass is ready: item index at a canvas pixel, or -1. */
export const picker: { pick: (x: number, y: number) => number } = { pick: () => -1 };

/** Render tuning the quality presets set (and the end-to-end tests read): point size multiplier. */
export const tuning = { pointScale: 1, minPx: 1.1 };

export const STILL =
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}
