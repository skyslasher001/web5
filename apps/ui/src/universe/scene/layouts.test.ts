import { describe, expect, it } from 'vitest';
import {
  CORE_CLEAR,
  fnv1a,
  galaxyFrame,
  graphLayout,
  mergeSemantic,
  projectLayout,
  timeLayout,
  type LayoutInput,
} from './layouts';

function input(n: number, galaxies = 3, links: [number, number][] = []): LayoutInput {
  const hashes = new Uint32Array(n);
  const galaxy = new Int16Array(n);
  const created = new Float64Array(n);
  const comet = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    hashes[i] = fnv1a(`item-${i}`);
    galaxy[i] = i % 10 === 9 ? -1 : i % galaxies;
    created[i] = 1_700_000_000 + i * 3600;
    comet[i] = i === n - 1 ? 1 : 0;
  }
  galaxy[n - 1] = -1;
  return {
    n,
    hashes,
    galaxy,
    created,
    comet,
    galaxyCount: galaxies,
    linksA: new Uint32Array(links.map((l) => l[0])),
    linksB: new Uint32Array(links.map((l) => l[1])),
  };
}

const at = (p: Float32Array, i: number) => [p[i * 3]!, p[i * 3 + 1]!, p[i * 3 + 2]!] as const;
const dist = (a: readonly number[], b: readonly number[]) =>
  Math.hypot(a[0]! - b[0]!, a[1]! - b[1]!, a[2]! - b[2]!);

describe('layouts', () => {
  it('places galaxies on a ring without overlaps', () => {
    const { centres, radii } = galaxyFrame([5000, 40, 900, 3, 120]);
    for (let a = 0; a < 5; a++) {
      for (let b = a + 1; b < 5; b++) {
        expect(dist(at(centres, a), at(centres, b))).toBeGreaterThan(radii[a]! + radii[b]!);
      }
      expect(Math.hypot(...at(centres, a))).toBeGreaterThan(radii[a]! + CORE_CLEAR);
    }
  });

  it('groups items in their galaxy, keeps the Core clear and puts comets at the edge', () => {
    const data = input(600);
    const result = projectLayout(data);
    for (let i = 0; i < data.n; i++) {
      const p = at(result.positions, i);
      expect(Math.hypot(...p)).toBeGreaterThan(CORE_CLEAR * 0.8);
      const g = data.galaxy[i]!;
      if (g >= 0)
        expect(dist(p, at(result.galaxyCentres, g))).toBeLessThanOrEqual(result.galaxyRadii[g]! * 1.05);
    }
    const comet = at(result.positions, data.n - 1);
    expect(Math.hypot(...comet)).toBeGreaterThan(Math.hypot(...at(result.galaxyCentres, 0)));
    expect(Math.hypot(...comet)).toBeLessThan(result.extent);
    // Deterministic.
    expect(projectLayout(data).positions).toEqual(result.positions);
  });

  it('winds the time spiral outward from the oldest item', () => {
    const data = input(300);
    const { positions } = timeLayout(data);
    const r = (i: number) => Math.hypot(at(positions, i)[0], at(positions, i)[2]);
    expect(r(299)).toBeGreaterThan(r(150));
    expect(r(150)).toBeGreaterThan(r(0));
  });

  it('pulls linked items together and leaves unlinked ones on the outer shell', () => {
    const links: [number, number][] = [
      [0, 1],
      [1, 2],
      [2, 0],
      [10, 11],
    ];
    const data = input(80, 2, links);
    const { positions } = graphLayout(data);
    const linkedSpan = dist(at(positions, 0), at(positions, 1));
    const unlinkedR = Math.hypot(...at(positions, 40));
    expect(linkedSpan).toBeLessThan(25);
    expect(unlinkedR).toBeGreaterThan(Math.hypot(...at(positions, 0)));
  });

  it('merges the Semantic layout and parks items without vectors outside it', () => {
    const data = input(4, 1);
    const index = new Map([
      ['a', 0],
      ['b', 1],
      ['c', 2],
      ['d', 3],
    ]);
    const result = mergeSemantic(data, index, ['a', 'b', 'gone'], [10, 0, 0, -10, 0, 0, 99, 99, 99]);
    expect(at(result.positions, 0)).toEqual([10, 0, 0]);
    expect(Math.hypot(...at(result.positions, 2))).toBeGreaterThan(30);
  });

  it('lays out 50k items quickly enough for a worker', () => {
    const links: [number, number][] = [];
    for (let k = 0; k < 14_000; k++) links.push([(k * 7919) % 50_000, (k * 104729 + 13) % 50_000]);
    const data = input(50_000, 12, links);
    const t0 = performance.now();
    projectLayout(data);
    const t1 = performance.now();
    graphLayout(data);
    const t2 = performance.now();
    console.log(`50k: project ${(t1 - t0).toFixed(0)} ms, graph ${(t2 - t1).toFixed(0)} ms`);
    expect(t1 - t0).toBeLessThan(1500);
    expect(t2 - t1).toBeLessThan(20_000);
  }, 120_000);
});
