import { describe, expect, it } from 'vitest';
import { linkPath } from './helpers';
import { buildScene, type SceneRow } from './sceneData';

const row = (id: string): SceneRow => ({
  id,
  type: 'note',
  title: id,
  galaxy: null,
  created: 1_700_000_000,
  captured: 1_700_000_000,
  opened: 0,
  opens: 0,
  status: 'active',
  ideaStage: null,
  pinned: false,
});

describe('pathways', () => {
  // a — b — c — d — e — f, and g on its own
  const scene = buildScene(
    ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map(row),
    { sources: ['a', 'b', 'c', 'd', 'e'], targets: ['b', 'c', 'd', 'e', 'f'], states: [] },
    [],
  );
  const i = (id: string) => scene.index.get(id)!;

  it('finds the shortest chain of links between two items', () => {
    expect(linkPath(scene, i('a'), i('d'))?.map((k) => scene.ids[k])).toEqual(['a', 'b', 'c', 'd']);
    expect(linkPath(scene, i('d'), i('a'))?.map((k) => scene.ids[k])).toEqual(['d', 'c', 'b', 'a']);
    expect(linkPath(scene, i('c'), i('c'))).toEqual([i('c')]);
  });

  it('gives up beyond the hop limit or when nothing connects them', () => {
    expect(linkPath(scene, i('a'), i('f'))).toBeNull(); // five links away
    expect(linkPath(scene, i('a'), i('f'), 5)).toHaveLength(6);
    expect(linkPath(scene, i('a'), i('g'))).toBeNull();
  });
});

describe('signal pulses', () => {
  it('travel their route one link per hop and stop on arrival', async () => {
    const { HOP_MS, pulseAt } = await import('./helpers');
    const { Vector3 } = await import('three');
    const route = [new Vector3(0, 0, 0), new Vector3(10, 0, 0), new Vector3(10, 10, 0)];
    const out = new Vector3();
    expect(pulseAt(route, HOP_MS / 2, out)?.toArray()).toEqual([5, 0, 0]);
    expect(pulseAt(route, HOP_MS * 1.5, out)?.toArray()).toEqual([10, 5, 0]);
    expect(pulseAt(route, HOP_MS * 2, out)).toBeNull();
    expect(pulseAt(route, -1, out)).toBeNull();
  });
});
