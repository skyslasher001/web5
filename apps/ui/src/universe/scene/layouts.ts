// The Project, Time and Graph layouts (ADR-0012): pure functions over typed arrays, run in a Web Worker.
// Deterministic: the same items always land in the same place, seeded by a hash of each item's id.
// The Semantic layout comes from Core (computed from embeddings) and is merged in by `mergeSemantic`.
import { forceLink, forceManyBody, forceSimulation, forceX, forceY, forceZ } from 'd3-force-3d';

export interface LayoutInput {
  n: number;
  hashes: Uint32Array; // fnv1a(id)
  galaxy: Int16Array; // galaxy index, -1 = none
  created: Float64Array; // epoch seconds
  comet: Uint8Array; // 1 = a fresh capture waiting for triage
  galaxyCount: number;
  linksA: Uint32Array;
  linksB: Uint32Array;
}

export interface LayoutResult {
  positions: Float32Array; // x, y, z per item
  galaxyCentres: Float32Array; // x, y, z per galaxy
  galaxyRadii: Float32Array;
  /** Radius that contains everything: where the camera starts and how far "home" is. */
  extent: number;
}

export const CORE_CLEAR = 22; // nothing sits closer to the Core than this
const GOLDEN = Math.PI * (3 - Math.sqrt(5));

export function fnv1a(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** A stable pseudo-random number in [0, 1) for this hash and salt. */
export function unit(hash: number, salt: number): number {
  let h = (hash ^ Math.imul(salt + 1, 0x9e3779b1)) >>> 0;
  h = Math.imul(h ^ (h >>> 16), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

/** Galaxy radius from its item count: big projects are big, without the largest swallowing the view. */
export function galaxyRadius(count: number): number {
  return 6 + 2.4 * Math.cbrt(Math.max(count, 0));
}

/** Galaxies on a ring around the Core, each given an arc proportional to its size, so none overlap. */
export function galaxyFrame(counts: number[]): { centres: Float32Array; radii: Float32Array; ring: number } {
  const g = counts.length;
  const radii = new Float32Array(counts.map(galaxyRadius));
  const centres = new Float32Array(g * 3);
  const total = radii.reduce((s, r) => s + 2 * r * 1.25, 0);
  const ring = Math.max(70, total / (2 * Math.PI), (radii.length ? Math.max(...radii) : 0) + CORE_CLEAR + 12);
  let arc = 0;
  for (let i = 0; i < g; i++) {
    const share = (2 * radii[i]! * 1.25) / Math.max(total, 1);
    const angle = (arc + share / 2) * Math.PI * 2 + Math.PI / 4;
    arc += share;
    const lift = Math.sin(i * 2.399) * ring * 0.08;
    centres.set([Math.cos(angle) * ring, lift, Math.sin(angle) * ring], i * 3);
  }
  return { centres, radii, ring };
}

function counts(input: LayoutInput): number[] {
  const c = new Array<number>(input.galaxyCount).fill(0);
  for (let i = 0; i < input.n; i++) {
    const g = input.galaxy[i]!;
    if (g >= 0 && !input.comet[i]) c[g]!++;
  }
  return c;
}

/** A point on a sphere shell (Fibonacci spiral), for loose items. */
function shell(k: number, m: number, radius: number, out: Float32Array, i: number) {
  const y = 1 - (2 * (k + 0.5)) / Math.max(m, 1);
  const r = Math.sqrt(Math.max(0, 1 - y * y));
  const theta = k * GOLDEN;
  out[i * 3] = Math.cos(theta) * r * radius;
  out[i * 3 + 1] = y * radius * 0.55; // a flattened halo reads better than a full sphere
  out[i * 3 + 2] = Math.sin(theta) * r * radius;
}

function placeComets(input: LayoutInput, out: Float32Array, edge: number) {
  for (let i = 0; i < input.n; i++) {
    if (!input.comet[i]) continue;
    const h = input.hashes[i]!;
    const angle = unit(h, 11) * Math.PI * 2;
    const r = edge * (1.05 + unit(h, 12) * 0.15);
    out[i * 3] = Math.cos(angle) * r;
    out[i * 3 + 1] = (unit(h, 13) - 0.5) * edge * 0.25;
    out[i * 3 + 2] = Math.sin(angle) * r;
  }
}

/** Project layout: items grouped in their galaxies as two-armed spirals; loose items in a halo; comets at the edge. */
export function projectLayout(input: LayoutInput): LayoutResult {
  const { n, hashes, galaxy } = input;
  const positions = new Float32Array(n * 3);
  const sizes = counts(input);
  const { centres, radii, ring } = galaxyFrame(sizes);
  // Rank each galaxy's members by age: the oldest form the core, new items the outer arms.
  const members: number[][] = sizes.map(() => []);
  const loose: number[] = [];
  for (let i = 0; i < n; i++) {
    if (input.comet[i]) continue;
    const g = galaxy[i]!;
    if (g >= 0) members[g]!.push(i);
    else loose.push(i);
  }
  members.forEach((list, g) => {
    list.sort((a, b) => input.created[a]! - input.created[b]! || hashes[a]! - hashes[b]!);
    const R = radii[g]!;
    const tiltX = Math.sin(g * 1.7) * 0.45;
    const tiltZ = Math.cos(g * 2.3) * 0.35;
    const [cx, cy, cz] = [centres[g * 3]!, centres[g * 3 + 1]!, centres[g * 3 + 2]!];
    list.forEach((i, k) => {
      const h = hashes[i]!;
      const f = Math.pow((k + 0.5) / list.length, 0.8);
      const r = R * (0.08 + 0.92 * f);
      const arm = h & 1;
      const angle = arm * Math.PI + f * 5.2 + (unit(h, 1) - 0.5) * 0.9;
      let x = Math.cos(angle) * r;
      let z = Math.sin(angle) * r;
      let y = (unit(h, 2) - 0.5) * R * 0.12 * (1.1 - f);
      // Tilt the disc so galaxies don't all face the same way.
      [y, z] = [y * Math.cos(tiltX) - z * Math.sin(tiltX), y * Math.sin(tiltX) + z * Math.cos(tiltX)];
      [x, y] = [x * Math.cos(tiltZ) - y * Math.sin(tiltZ), x * Math.sin(tiltZ) + y * Math.cos(tiltZ)];
      positions.set([cx + x, cy + y, cz + z], i * 3);
    });
  });
  const halo = CORE_CLEAR + Math.min(ring * 0.35, 8 + Math.cbrt(loose.length) * 2.5);
  loose
    .sort((a, b) => hashes[a]! - hashes[b]!)
    .forEach((i, k) => {
      shell(k, loose.length, halo * (0.85 + unit(hashes[i]!, 3) * 0.3), positions, i);
    });
  const maxR = radii.length ? Math.max(...radii) : 0;
  const edge = ring + maxR + 30;
  placeComets(input, positions, edge);
  return { positions, galaxyCentres: centres, galaxyRadii: radii, extent: edge * 1.2 };
}

/** Time layout: one spiral by creation date, oldest at the centre. The time slider replays it growing. */
export function timeLayout(input: LayoutInput): LayoutResult {
  const { n, hashes } = input;
  const positions = new Float32Array(n * 3);
  const order = Array.from({ length: n }, (_, i) => i).sort(
    (a, b) => input.created[a]! - input.created[b]! || hashes[a]! - hashes[b]!,
  );
  const turns = 6;
  const outer = 60 + 40 * Math.cbrt(n);
  order.forEach((i, rank) => {
    const t = n > 1 ? rank / (n - 1) : 0;
    const h = hashes[i]!;
    const angle = t * turns * Math.PI * 2;
    const r = CORE_CLEAR + (outer - CORE_CLEAR) * t + (unit(h, 4) - 0.5) * 6;
    positions.set(
      [Math.cos(angle) * r, (unit(h, 5) - 0.5) * 6 + (t - 0.5) * outer * 0.15, Math.sin(angle) * r],
      i * 3,
    );
  });
  return { positions, ...centroidsOf(positions, input), extent: outer * 1.25 };
}

/** Graph layout: force-directed on links, with each galaxy as a hub its members are loosely tied to.
 * Items without links rest on a dim outer shell, so 50k unlinked items don't drown the graph. */
export function graphLayout(input: LayoutInput, maxTicks = 160): LayoutResult {
  const { n, hashes, galaxy, linksA, linksB } = input;
  const positions = new Float32Array(n * 3);
  const linked = new Uint8Array(n);
  for (let k = 0; k < linksA.length; k++) {
    linked[linksA[k]!] = 1;
    linked[linksB[k]!] = 1;
  }
  interface Node {
    index?: number;
    x?: number;
    y?: number;
    z?: number;
    item: number; // -1 for a galaxy hub
  }
  const nodes: Node[] = [];
  const nodeOf = new Int32Array(n).fill(-1);
  const hubs: number[] = [];
  // Start every node where the Project layout puts it (pulled in toward the Core): the graph is mostly
  // clustered already, so a few dozen ticks refine it instead of hundreds untangling noise.
  const start = projectLayout(input);
  const pull = 0.6;
  for (let g = 0; g < input.galaxyCount; g++) {
    hubs.push(nodes.length);
    const c = start.galaxyCentres;
    nodes.push({ item: -1, x: c[g * 3]! * pull, y: c[g * 3 + 1]! * pull, z: c[g * 3 + 2]! * pull });
  }
  for (let i = 0; i < n; i++) {
    if (!linked[i]) continue;
    nodeOf[i] = nodes.length;
    const p = start.positions;
    nodes.push({ item: i, x: p[i * 3]! * pull, y: p[i * 3 + 1]! * pull, z: p[i * 3 + 2]! * pull });
  }
  const edges: { source: number; target: number; strength: number }[] = [];
  for (let k = 0; k < linksA.length; k++) {
    edges.push({ source: nodeOf[linksA[k]!]!, target: nodeOf[linksB[k]!]!, strength: 0.7 });
  }
  for (let i = 0; i < n; i++) {
    if (nodeOf[i]! >= 0 && galaxy[i]! >= 0)
      edges.push({ source: nodeOf[i]!, target: hubs[galaxy[i]!]!, strength: 0.04 });
  }
  if (nodes.length) {
    // About half a million node-ticks: ~10 s at 20k linked items in a worker, far less for a normal vault.
    const ticks = Math.max(12, Math.min(maxTicks, Math.round(500_000 / Math.max(nodes.length, 1))));
    const sim = forceSimulation(nodes, 3)
      .force(
        'link',
        forceLink(edges)
          .distance(7)
          .strength((e: { strength: number }) => e.strength),
      )
      .force('charge', forceManyBody().strength(-9).theta(1.1).distanceMax(90))
      .force('x', forceX(0).strength(0.015))
      .force('y', forceY(0).strength(0.015))
      .force('z', forceZ(0).strength(0.015))
      .stop();
    sim.tick(ticks);
  }
  let extent = CORE_CLEAR;
  for (const node of nodes) {
    if (node.item < 0) continue;
    const [x, y, z] = [node.x ?? 0, node.y ?? 0, node.z ?? 0];
    positions.set([x, y, z], node.item * 3);
    extent = Math.max(extent, Math.hypot(x, y, z));
  }
  const unlinked: number[] = [];
  for (let i = 0; i < n; i++) if (!linked[i]) unlinked.push(i);
  unlinked
    .sort((a, b) => hashes[a]! - hashes[b]!)
    .forEach((i, k) =>
      shell(k, unlinked.length, (extent + 40) * (0.95 + unit(hashes[i]!, 9) * 0.1), positions, i),
    );
  return { positions, ...centroidsOf(positions, input), extent: (extent + 40) * 1.25 };
}

/** Galaxy centres and radii as the centroid and spread of their members (for layouts that don't group). */
export function centroidsOf(
  positions: Float32Array,
  input: Pick<LayoutInput, 'n' | 'galaxy' | 'galaxyCount'>,
): Pick<LayoutResult, 'galaxyCentres' | 'galaxyRadii'> {
  const g = input.galaxyCount;
  const sum = new Float64Array(g * 3);
  const count = new Float64Array(g);
  for (let i = 0; i < input.n; i++) {
    const k = input.galaxy[i]!;
    if (k < 0) continue;
    sum[k * 3] = sum[k * 3]! + positions[i * 3]!;
    sum[k * 3 + 1] = sum[k * 3 + 1]! + positions[i * 3 + 1]!;
    sum[k * 3 + 2] = sum[k * 3 + 2]! + positions[i * 3 + 2]!;
    count[k] = count[k]! + 1;
  }
  const galaxyCentres = new Float32Array(g * 3);
  for (let k = 0; k < g; k++) {
    if (count[k]) for (let a = 0; a < 3; a++) galaxyCentres[k * 3 + a] = sum[k * 3 + a]! / count[k]!;
  }
  const spread = new Float64Array(g);
  for (let i = 0; i < input.n; i++) {
    const k = input.galaxy[i]!;
    if (k < 0) continue;
    spread[k] =
      spread[k]! +
      Math.hypot(
        positions[i * 3]! - galaxyCentres[k * 3]!,
        positions[i * 3 + 1]! - galaxyCentres[k * 3 + 1]!,
        positions[i * 3 + 2]! - galaxyCentres[k * 3 + 2]!,
      );
  }
  const galaxyRadii = new Float32Array(g);
  for (let k = 0; k < g; k++) galaxyRadii[k] = count[k] ? Math.max(6, (spread[k]! / count[k]!) * 1.4) : 6;
  return { galaxyCentres, galaxyRadii };
}

/** Semantic layout from Core: known items take Core's positions; items without vectors yet wait on a dim
 * outer shell until they're embedded. */
export function mergeSemantic(
  input: LayoutInput,
  index: Map<string, number>,
  ids: string[],
  flat: number[],
): LayoutResult {
  const positions = new Float32Array(input.n * 3);
  const placed = new Uint8Array(input.n);
  let extent = CORE_CLEAR;
  ids.forEach((id, k) => {
    const i = index.get(id);
    if (i === undefined) return;
    const x = flat[k * 3]!;
    const y = flat[k * 3 + 1]!;
    const z = flat[k * 3 + 2]!;
    positions.set([x, y, z], i * 3);
    placed[i] = 1;
    extent = Math.max(extent, Math.hypot(x, y, z));
  });
  const waiting: number[] = [];
  for (let i = 0; i < input.n; i++) if (!placed[i]) waiting.push(i);
  waiting.forEach((i, k) => shell(k, waiting.length, extent + 35, positions, i));
  return { positions, ...centroidsOf(positions, input), extent: (extent + 35) * 1.25 };
}
