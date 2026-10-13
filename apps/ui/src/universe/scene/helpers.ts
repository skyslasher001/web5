// Pure helpers for the scene (unit-tested): item appearance, link segments, galaxy activity, nearest
// items, flight timing and a deterministic PRNG.
import type { ItemType } from '@universe/shared-types';
import { Vector3 } from 'three';
import { useLayout } from './layoutController';
import type { SceneData } from './sceneData';
import { styleFor, TYPE_ORDER } from './types';

const DAY = 86_400;

/** Importance → size and brightness (SPEC §7: brighter when recently opened; forgotten items dim). */
export function appearance(scene: SceneData, i: number, now: number): { size: number; glow: number } {
  const type = TYPE_ORDER[scene.types[i]!]! as ItemType;
  const style = styleFor(type, scene.ideaStages[i] ?? null);
  const opens = scene.opens[i]!;
  const size = 0.6 * style.size * (1 + 0.22 * Math.log2(1 + opens) + (scene.pinned[i] ? 0.35 : 0));
  const lastTouch = Math.max(scene.opened[i]!, scene.created[i]!);
  const age = (now - lastTouch) / DAY;
  const glow = scene.comet[i] ? 1 : age < 30 ? 1 : age > 180 ? 0.42 : 0.78;
  return { size, glow };
}

/** Line-segment vertices for the links `keep` accepts. */
export function linkSegments(
  positions: Float32Array,
  a: Uint32Array,
  b: Uint32Array,
  keep: (k: number) => boolean,
): Float32Array {
  const out: number[] = [];
  for (let k = 0; k < a.length; k++) {
    if (!keep(k)) continue;
    const i = a[k]!;
    const j = b[k]!;
    out.push(
      positions[i * 3]!,
      positions[i * 3 + 1]!,
      positions[i * 3 + 2]!,
      positions[j * 3]!,
      positions[j * 3 + 1]!,
      positions[j * 3 + 2]!,
    );
  }
  return new Float32Array(out);
}

/** Share of a galaxy's items created or opened in the last 30 days (its "recent activity"). */
export function galaxyActivity(scene: SceneData, now = Date.now() / 1000): Float32Array {
  const g = scene.galaxyIds.length;
  const recent = new Float32Array(g);
  const total = new Float32Array(g);
  for (let i = 0; i < scene.n; i++) {
    const k = scene.galaxy[i]!;
    if (k < 0) continue;
    total[k] = total[k]! + 1;
    if (now - Math.max(scene.created[i]!, scene.opened[i]!) < 30 * DAY) recent[k] = recent[k]! + 1;
  }
  return recent.map((r, k) => (total[k] ? r / total[k]! : 0));
}

/** Indices of the `k` nearest items within `maxDistance` in front of the camera (brute force, ≈1 ms at 50k). */
export function nearestInFront(
  positions: Float32Array,
  camera: { x: number; y: number; z: number },
  forward: { x: number; y: number; z: number },
  k: number,
  maxDistance: number,
): number[] {
  const best: { i: number; d: number }[] = [];
  const max2 = maxDistance * maxDistance;
  const n = positions.length / 3;
  for (let i = 0; i < n; i++) {
    const dx = positions[i * 3]! - camera.x;
    const dy = positions[i * 3 + 1]! - camera.y;
    const dz = positions[i * 3 + 2]! - camera.z;
    const d = dx * dx + dy * dy + dz * dz;
    if (d > max2 || dx * forward.x + dy * forward.y + dz * forward.z <= 0) continue;
    if (best.length < k) {
      best.push({ i, d });
      if (best.length === k) best.sort((p, q) => p.d - q.d);
    } else if (d < best[k - 1]!.d) {
      best[k - 1] = { i, d };
      best.sort((p, q) => p.d - q.d);
    }
  }
  return best.sort((p, q) => p.d - q.d).map((b) => b.i);
}

/** 600 ms for a hop, up to 1200 ms across the universe (SPEC §7). */
export function flightDuration(travel: number): number {
  return Math.round(Math.min(1200, 600 + travel * 1.6));
}

/** Deterministic PRNG so the starfield is identical on every launch. */
export function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Where an item is in the current layout. */
export function itemPosition(index: number): Vector3 | null {
  const layout = useLayout.getState().current;
  if (!layout || index < 0 || index * 3 + 2 >= layout.positions.length) return null;
  const p = layout.positions;
  return new Vector3(p[index * 3], p[index * 3 + 1], p[index * 3 + 2]);
}

/** Imperative camera API, filled in by CameraRig (and read by the minimap and end-to-end tests). */
export const rig = {
  flyTo: (_target: Vector3, _distance: number): void => {},
  home: (): void => {},
  state: () => ({ position: [0, 0, 0] as number[], target: [0, 0, 0] as number[], flying: false }),
};
