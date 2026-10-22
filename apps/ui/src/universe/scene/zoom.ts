// Smooth, scalable zoom (pure helpers, unit-tested). Zoom works on a log scale: every wheel notch multiplies
// the camera distance by the same factor, so going from the whole universe down to one item takes the same
// effort per order of magnitude. The camera eases toward the goal (frame-rate independent) and zooms toward
// whatever is under the pointer, so the thing you point at stays under the pointer.

export interface V3 {
  x: number;
  y: number;
  z: number;
}

/** One mouse-wheel notch (100 px) changes the distance by this factor. */
export const NOTCH = 1.2;
/** How fast the camera closes on the zoom goal (per second, exponential). */
export const ZOOM_RATE = 14;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/**
 * The distance factor for one wheel event: > 1 zooms out, < 1 zooms in. `deltaMode` 1 is lines and 2 is
 * pages (some mice and Windows settings), 0 is pixels. A touchpad pinch arrives as a wheel event with
 * `ctrlKey` set and small deltas, so it gets a finer scale. One event never moves more than three notches.
 */
export function wheelFactor(deltaY: number, deltaMode: number, pinch: boolean): number {
  const px = deltaMode === 1 ? deltaY * 33 : deltaMode === 2 ? deltaY * 800 : deltaY;
  const perPx = pinch ? 0.012 : Math.log(NOTCH) / 100;
  return Math.exp(clamp(px * perPx, -3 * Math.log(NOTCH), 3 * Math.log(NOTCH)));
}

/** Closest and farthest camera distances for a layout of this size (it always fits on screen). */
export function zoomLimits(extent: number): { min: number; max: number } {
  return { min: 0.8, max: Math.max(600, extent * 5) };
}

/**
 * One frame of easing from `current` to `goal`, on the log scale so zooming in and out feel the same.
 * Snaps to the goal once it's within 0.1 %.
 */
export function easeToward(current: number, goal: number, dtSeconds: number, rate = ZOOM_RATE): number {
  if (!(current > 0) || !Number.isFinite(rate)) return goal;
  const k = 1 - Math.exp(-rate * Math.max(0, Math.min(dtSeconds, 0.25)));
  const next = Math.exp(Math.log(current) + (Math.log(goal) - Math.log(current)) * k);
  return Math.abs(Math.log(next / goal)) < 0.001 ? goal : next;
}

/** The orbit target after scaling the distance by `ratio` around `anchor` (the point under the pointer). */
export function zoomAnchor(target: V3, anchor: V3, ratio: number): V3 {
  return {
    x: anchor.x + (target.x - anchor.x) * ratio,
    y: anchor.y + (target.y - anchor.y) * ratio,
    z: anchor.z + (target.z - anchor.z) * ratio,
  };
}

/**
 * Near and far clip planes that keep depth precision at every zoom (from 1 unit away to the whole universe).
 * The far plane never comes closer than the starfield (Backdrop.tsx: up to 6000 units from the camera).
 */
export function clipPlanes(distance: number): { near: number; far: number } {
  return { near: clamp(distance * 0.004, 0.02, 2), far: clamp(distance * 40, 8000, 80000) };
}

/** Distance ↔ 0–1 on the log scale (0 = closest), for the zoom slider. */
export function zoomFraction(distance: number, min: number, max: number): number {
  return clamp(Math.log(distance / min) / Math.log(max / min), 0, 1);
}

export function distanceAt(fraction: number, min: number, max: number): number {
  return min * Math.pow(max / min, clamp(fraction, 0, 1));
}

/**
 * The galaxy the camera has zoomed into without selecting it: the orbit target is inside the galaxy and the
 * camera is close enough that its stars fill the view. -1 when none. Only meaningful in the Project layout.
 */
/**
 * The next zoom goal. `by` scales the goal already in flight, so quick wheel notches add up; `to` is a
 * point on the 0–1 log scale (the zoom slider).
 */
export function zoomGoal(
  request: { by: number } | { to: number },
  inFlight: number | null,
  distance: number,
  min: number,
  max: number,
): number {
  if ('to' in request) return clamp(distanceAt(request.to, min, max), min, max);
  return clamp((inFlight ?? distance) * request.by, min, max);
}

export function focusGalaxy(
  target: V3,
  distance: number,
  centres: Float32Array,
  radii: Float32Array,
): number {
  let best = -1;
  let bestD = Infinity;
  for (let g = 0; g < radii.length; g++) {
    const r = radii[g]!;
    const dx = target.x - centres[g * 3]!;
    const dy = target.y - centres[g * 3 + 1]!;
    const dz = target.z - centres[g * 3 + 2]!;
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (d < r * 1.1 && distance < r * 3.5 && d < bestD) {
      best = g;
      bestD = d;
    }
  }
  return best;
}
