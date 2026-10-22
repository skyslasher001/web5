// Pure helpers for the scene (unit-tested): item appearance, link segments, galaxy activity, nearest
// items, flight timing and a deterministic PRNG.
import type { ItemType } from '@universe/shared-types';
import { Vector3 } from 'three';
import { useLayout } from './layoutController';
import { useScene, type SceneData } from './sceneData';
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

/** Where an item is in the current layout (null while the layout is for an older scene version). */
export function itemPosition(index: number): Vector3 | null {
  const layout = useLayout.getState().current;
  if (!layout || layout.sceneVersion !== useScene.getState().version) return null;
  if (index < 0 || index * 3 + 2 >= layout.positions.length) return null;
  const p = layout.positions;
  return new Vector3(p[index * 3], p[index * 3 + 1], p[index * 3 + 2]);
}

/**
 * A camera flight to a selection, once per `key` (the selection and the layout kind; null when nothing is
 * selected). `fly` returns false while the target isn't placed yet (its layout is still computing), so the
 * run after the matching layout arrives flies; a later data refresh with the same key leaves the camera be.
 */
export function flyOnce(flown: { current: string }, key: string | null, fly: () => boolean): void {
  if (key === null) {
    flown.current = '';
    return;
  }
  if (flown.current === key) return;
  if (fly()) flown.current = key;
}

function idleRig() {
  return {
    flyTo: (_target: Vector3, _distance: number): void => {},
    home: (): void => {},
    /** Smooth zoom by a distance factor (> 1 out, < 1 in), toward the centre of the view. */
    zoomBy: (_factor: number): void => {},
    /** Smooth zoom to a point on the 0–1 log scale (0 = closest). */
    zoomTo: (_fraction: number): void => {},
    /** Where the zoom is on the 0–1 log scale, and the galaxy zoomed into (its index, -1 none). */
    zoom: (): { fraction: number; galaxy: number } => ({ fraction: 1, galaxy: -1 }),
    state: () => ({
      position: [0, 0, 0] as number[],
      target: [0, 0, 0] as number[],
      flying: false,
      /** The last finished flight: planned and actual duration (ms). */
      lastFlight: null as { planned: number; actual: number } | null,
    }),
  };
}

/** Imperative camera API, filled in by CameraRig (and read by the minimap and end-to-end tests). */
export const rig = idleRig();

/** A scene unmounted: nothing may keep calling into its disposed camera. */
export function resetRig(): void {
  Object.assign(rig, idleRig());
}

/** Universe → Galaxy → System (an item and its neighbours) → Item (its viewer is open) (SPEC §7). */
export type ZoomLevel = 'Universe' | 'Galaxy' | 'System' | 'Item';

/** The selection decides the level; without one, zooming into a galaxy is enough to be at Galaxy level. */
export function zoomLevel(
  s: {
    viewerItemId: string | null;
    selectedItemId: string | null;
    selectedProjectId: string | null;
  },
  zoomedIntoGalaxy = false,
): ZoomLevel {
  if (s.viewerItemId) return 'Item';
  if (s.selectedItemId) return 'System';
  if (s.selectedProjectId || zoomedIntoGalaxy) return 'Galaxy';
  return 'Universe';
}

/** Photo textures kept on the GPU at most (least recently shown go first). */
export const MAX_TEXTURES = 64;

/** Ids to evict so at most `max` textures stay, oldest first, never one on screen. `order` is oldest first. */
export function texturesToEvict(order: string[], onScreen: Set<string>, max = MAX_TEXTURES): string[] {
  const out: string[] = [];
  let extra = order.length - max;
  for (const id of order) {
    if (extra <= 0) break;
    if (onScreen.has(id)) continue;
    out.push(id);
    extra--;
  }
  return out;
}

const adjacency = new WeakMap<SceneData, Map<number, number[]>>();

/**
 * The shortest chain of links from item `from` to item `to` (item indices, both ends included), at most
 * `maxHops` links long; null when they aren't connected that closely. Signal pulses and agent probes travel
 * it, so you see a thought move along the pathways (SPEC §7, §10). Breadth-first over the scene's links.
 */
export function linkPath(scene: SceneData, from: number, to: number, maxHops = 4): number[] | null {
  if (from === to) return [from];
  let adj = adjacency.get(scene);
  if (!adj) {
    adj = new Map();
    for (let k = 0; k < scene.linksA.length; k++) {
      const a = scene.linksA[k]!;
      const b = scene.linksB[k]!;
      (adj.get(a) ?? adj.set(a, []).get(a)!).push(b);
      (adj.get(b) ?? adj.set(b, []).get(b)!).push(a);
    }
    adjacency.set(scene, adj);
  }
  const parent = new Map<number, number>([[from, -1]]);
  let frontier = [from];
  for (let hop = 0; hop < maxHops && frontier.length; hop++) {
    const next: number[] = [];
    for (const node of frontier) {
      for (const n of adj.get(node) ?? []) {
        if (parent.has(n)) continue;
        parent.set(n, node);
        if (n === to) {
          const path = [to];
          for (let p = node; p !== -1; p = parent.get(p)!) path.unshift(p);
          return path;
        }
        next.push(n);
      }
    }
    frontier = next;
  }
  return null;
}

/** One link of a signal pulse's route (Pulses.tsx). */
export const HOP_MS = 380;

/** Where a pulse is `ms` after it started: along its route, one hop per HOP_MS. Null once it has arrived. */
export function pulseAt(route: Vector3[], ms: number, out: Vector3): Vector3 | null {
  if (ms < 0 || route.length < 2) return null;
  const hop = Math.floor(ms / HOP_MS);
  if (hop >= route.length - 1) return null;
  const t = (ms - hop * HOP_MS) / HOP_MS;
  return out.lerpVectors(route[hop]!, route[hop + 1]!, t);
}
