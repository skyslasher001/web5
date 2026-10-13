import type { CoreEvent } from '@universe/shared-types';
import { describe, expect, it } from 'vitest';
import { applyProbeTarget } from '../../state/store';
import { appearance, flightDuration, galaxyActivity, linkSegments, nearestInFront } from './helpers';
import { pickColor, pickIndex } from './shaders';
import { buildScene, COMET_DAYS, ideaStageCode, type SceneRow } from './sceneData';
import { Shape, styleFor } from './types';
import { resultIndices } from './useConstellation';

const NOW = 1_800_000_000;
const DAY = 86_400;

function row(id: string, over: Partial<SceneRow> = {}): SceneRow {
  return {
    id,
    type: 'note',
    title: id,
    galaxy: null,
    created: NOW - 400 * DAY,
    captured: NOW - 400 * DAY,
    opened: 0,
    opens: 0,
    status: 'active',
    ideaStage: null,
    pinned: false,
    ...over,
  };
}

describe('scene data', () => {
  it('builds typed arrays, galaxies, comets and links', () => {
    const rows = [
      row('b', { galaxy: 'g1' }),
      row('a', { galaxy: 'g2' }),
      row('c', { status: 'inbox', created: NOW - DAY }),
      row('d', { status: 'inbox', created: NOW - (COMET_DAYS + 1) * DAY }),
      row('e', { galaxy: 'new-galaxy' }),
    ];
    const scene = buildScene(
      rows,
      {
        sources: ['a', 'b', 'gone'],
        targets: ['b', 'c', 'a'],
        states: ['confirmed', 'suggested', 'confirmed'],
      },
      ['g1', 'g2'],
      NOW,
    );
    expect(scene.ids).toEqual(['a', 'b', 'c', 'd', 'e']); // sorted: stable across refreshes
    expect([...scene.galaxy]).toEqual([1, 0, -1, -1, 2]);
    expect(scene.galaxyIds).toEqual(['g1', 'g2', 'new-galaxy']);
    expect([...scene.comet]).toEqual([0, 0, 1, 0, 0]); // only a fresh inbox item without a galaxy
    expect([...scene.linksA]).toEqual([0, 1]);
    expect([...scene.linkSuggested]).toEqual([0, 1]);
    expect(ideaStageCode('protostar')).toBe(2);
  });

  it('maps importance to size and recency to brightness', () => {
    const scene = buildScene(
      [row('old'), row('fresh', { opened: NOW - DAY, opens: 15 }), row('pinned', { pinned: true })],
      { sources: [], targets: [], states: [] },
      [],
      NOW,
    );
    const at = (id: string) => appearance(scene, scene.index.get(id)!, NOW);
    expect(at('fresh').size).toBeGreaterThan(at('old').size);
    expect(at('pinned').size).toBeGreaterThan(at('old').size);
    expect(at('fresh').glow).toBe(1);
    expect(at('old').glow).toBeLessThan(0.5); // forgotten: a dim star
  });

  it('measures galaxy activity', () => {
    const scene = buildScene(
      [row('a', { galaxy: 'g', created: NOW - DAY }), row('b', { galaxy: 'g' })],
      { sources: [], targets: [], states: [] },
      ['g'],
      NOW,
    );
    expect(galaxyActivity(scene, NOW)[0]).toBeCloseTo(0.5);
  });
});

describe('celestial mapping', () => {
  it('gives every type a shape, and ideas mature', () => {
    expect(styleFor('photo', null).shape).toBe(Shape.planet);
    expect(styleFor('song', null).shape).toBe(Shape.pulsar);
    expect(styleFor('code_repo', null).body).toBe('space station');
    expect(styleFor('idea', 'nebula').shape).toBe(Shape.nebula);
    expect(styleFor('idea', 'protostar').shape).toBe(Shape.protostar);
    expect(styleFor('idea', 'star').shape).toBe(Shape.star);
  });

  it('round-trips pick colours', () => {
    for (const i of [0, 1, 255, 256, 65_535, 49_999, 1_000_000]) {
      const [r, g, b] = pickColor(i).map((c) => Math.round(c * 255));
      expect(pickIndex(r!, g!, b!)).toBe(i);
    }
  });
});

describe('scene helpers', () => {
  it('finds the nearest items in front of the camera', () => {
    const positions = new Float32Array([0, 0, -5, 0, 0, -1, 0, 0, 5, 0, 0, -50]);
    const found = nearestInFront(positions, { x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: -1 }, 2, 20);
    expect(found).toEqual([1, 0]); // behind the camera and beyond reach are skipped
  });

  it('times flights between 600 and 1200 ms', () => {
    expect(flightDuration(0)).toBe(600);
    expect(flightDuration(100)).toBe(760);
    expect(flightDuration(10_000)).toBe(1200);
  });

  it('builds filament segments for the links it keeps', () => {
    const positions = new Float32Array([0, 0, 0, 1, 1, 1, 2, 2, 2]);
    const segments = linkSegments(
      positions,
      new Uint32Array([0, 1]),
      new Uint32Array([1, 2]),
      (k) => k === 1,
    );
    expect([...segments]).toEqual([1, 1, 1, 2, 2, 2]);
  });

  it('turns search hits into a ranked constellation', () => {
    const index = new Map([
      ['x', 3],
      ['y', 7],
    ]);
    expect(resultIndices(['y', 'missing', 'x'], index)).toEqual([7, 3]);
    expect(resultIndices(['y', 'x'], index, 1)).toEqual([7]);
  });

  it('sends a probe to what the tool works on and home when the task ends', () => {
    const ev = (type: string, payload: Record<string, unknown>) =>
      ({ type, payload }) as unknown as CoreEvent;
    let targets = applyProbeTarget(
      {},
      ev('agent.step', { agent_id: 'librarian', target: { kind: 'item', id: 'i1' } }),
    );
    expect(targets).toEqual({ librarian: { kind: 'item', id: 'i1' } });
    targets = applyProbeTarget(targets, ev('agent.step', { agent_id: 'librarian', kind: 'llm_call' }));
    expect(targets.librarian?.id).toBe('i1'); // a model call keeps the last target
    targets = applyProbeTarget(targets, ev('agent.completed', { agent_id: 'librarian' }));
    expect(targets).toEqual({});
  });
});
