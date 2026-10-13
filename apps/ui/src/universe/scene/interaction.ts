// Shared, non-React state for the scene: the GPU picker, what's under the pointer, and the search
// constellation (result indices, in result order).
import { create } from 'zustand';

interface Interaction {
  hovered: number; // item index under the pointer, -1 none
  /** Search results shown as a constellation: item indices in rank order. */
  results: number[];
  setHovered(index: number): void;
  setResults(results: number[]): void;
}

export const useInteraction = create<Interaction>()((set) => ({
  hovered: -1,
  results: [],
  setHovered: (hovered) => set((s) => (s.hovered === hovered ? s : { hovered })),
  setResults: (results) => set({ results }),
}));

/** Set by ItemPoints once the GPU picking pass is ready: item index at a canvas pixel, or -1. */
export const picker: { pick: (x: number, y: number) => number } = { pick: () => -1 };

/** Render tuning the quality presets set (and the end-to-end tests read): point size multiplier. */
export const tuning = { pointScale: 1, minPx: 1.1 };

export const STILL =
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}
