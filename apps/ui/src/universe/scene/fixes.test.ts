// Regression tests for the Phase 4 review fixes in the scene (data refresh, search, textures).
import type { CoreEvent } from '@universe/shared-types';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CoreApi } from '../../lib/api';
import { flyOnce, itemPosition, resetRig, rig, texturesToEvict } from './helpers';
import { enterTarget } from './interaction';
import { useLayout } from './layoutController';
import { emptyScene, SceneLoader, useScene } from './sceneData';
import { shouldAutoSelect } from './useConstellation';

function page(ids: string[], serverTime: string, next: string | null = null) {
  return {
    ids,
    types: ids.map(() => 'note'),
    titles: ids,
    galaxies: ids.map(() => null),
    created: ids.map(() => 1_700_000_000),
    captured: ids.map(() => 1_700_000_000),
    opened: ids.map(() => 0),
    opens: ids.map(() => 0),
    statuses: ids.map(() => 'active'),
    idea_stages: ids.map(() => null),
    pinned: ids.map(() => false),
    removed: [] as string[],
    next_cursor: next,
    total: ids.length,
    server_time: serverTime,
  };
}

const event = (type: string) => ({ type }) as unknown as CoreEvent;

afterEach(() => {
  vi.useRealTimers();
});

describe('incremental scene refresh', () => {
  it('resumes from the first page of a multi-page refresh, so rows changed meanwhile come again', async () => {
    vi.useFakeTimers();
    const calls: (string | null | undefined)[] = [];
    const pages: Record<string, ReturnType<typeof page>> = {
      'load:': page(['a'], 'T0'),
      'since:': page(['b'], 'T1', '2'),
      'since:2': page(['c'], 'T2'),
    };
    const api = {
      universeLinks: async () => ({ ids: [], sources: [], targets: [], kinds: [], states: [] }),
      universeItems: async ({ cursor, since }: { cursor?: string | null; since?: string | null }) => {
        calls.push(since);
        return pages[`${since ? 'since' : 'load'}:${cursor ?? ''}`]!;
      },
    } as unknown as CoreApi;
    const loader = new SceneLoader(api);
    await loader.load();
    loader.onEvent(event('item.updated'));
    await vi.advanceTimersByTimeAsync(1300);
    expect(useScene.getState().scene.n).toBe(3);
    pages['since:'] = page([], 'T9');
    loader.onEvent(event('item.updated'));
    await vi.advanceTimersByTimeAsync(1300);
    expect(calls.at(-1)).toBe('T1'); // not T2, the last page's time
  });

  it('runs again for events that arrived while a refresh was running', async () => {
    vi.useFakeTimers();
    let release: () => void = () => {};
    let refreshes = 0;
    const api = {
      universeLinks: async () => ({ ids: [], sources: [], targets: [], kinds: [], states: [] }),
      universeItems: async ({ since }: { since?: string | null }) => {
        if (!since) return page(['a'], 'T0');
        refreshes++;
        if (refreshes === 1) await new Promise<void>((r) => (release = r));
        return page([`n${refreshes}`], `T${refreshes}`);
      },
    } as unknown as CoreApi;
    const loader = new SceneLoader(api);
    await loader.load();
    loader.onEvent(event('item.created'));
    await vi.advanceTimersByTimeAsync(1300); // the first refresh starts and waits
    loader.onEvent(event('item.created')); // arrives while it runs
    await vi.advanceTimersByTimeAsync(1300); // its timer fires while the first is still busy
    release();
    await vi.advanceTimersByTimeAsync(1300);
    expect(refreshes).toBe(2);
    expect(useScene.getState().scene.ids).toContain('n2');
  });
});

describe('full scene loads (start and every reconnect)', () => {
  const noLinks = async () => ({ ids: [], sources: [], targets: [], kinds: [], states: [] });

  it('keep showing the whole scene while a reload reads its pages', async () => {
    let reload = false;
    const api = {
      universeLinks: noLinks,
      universeItems: async ({ cursor }: { cursor?: string | null }) =>
        !reload ? page(['a', 'b', 'c'], 'T0') : cursor ? page(['c'], 'T1') : page(['a', 'b'], 'T1', '2'),
    } as unknown as CoreApi;
    const loader = new SceneLoader(api);
    await loader.load();
    expect(useScene.getState().scene.n).toBe(3);
    const shown: number[] = [];
    const stop = useScene.subscribe((s) => shown.push(s.scene.n));
    reload = true;
    await loader.load(); // Core came back
    stop();
    expect(Math.min(...shown)).toBe(3); // never shrank to the first page
    expect(useScene.getState().scene.ids).toEqual(['a', 'b', 'c']);
  });

  it('let only the newest of two overlapping loads write the scene', async () => {
    let release: () => void = () => {};
    let loads = 0;
    const api = {
      universeLinks: noLinks,
      universeItems: async ({ cursor }: { cursor?: string | null }) => {
        if (cursor === 'old-2') {
          await new Promise<void>((r) => (release = r));
          return page(['gone'], 'T0');
        }
        loads++;
        return loads === 1 ? page(['a'], 'T0', 'old-2') : page(['x'], 'T1');
      },
    } as unknown as CoreApi;
    const loader = new SceneLoader(api);
    const first = loader.load();
    await new Promise((r) => setTimeout(r, 0)); // the first load waits on its second page
    await loader.load(); // a reconnect starts another one, which finishes first
    release();
    await first;
    expect(useScene.getState().scene.ids).toEqual(['x']);
    expect(useScene.getState().loading).toBe(false);
  });

  it('retry a first load that failed when the next event arrives', async () => {
    vi.useFakeTimers();
    let up = false;
    const api = {
      universeLinks: noLinks,
      universeItems: async () => {
        if (!up) throw new Error('Core is restarting');
        return page(['a'], 'T0');
      },
    } as unknown as CoreApi;
    useScene.setState({ scene: emptyScene() });
    const loader = new SceneLoader(api);
    await loader.load();
    expect(useScene.getState().error).toBe('Core is restarting');
    up = true;
    loader.onEvent(event('item.created'));
    await vi.advanceTimersByTimeAsync(1300);
    expect(useScene.getState().scene.ids).toEqual(['a']);
    expect(useScene.getState().error).toBeNull();
  });
});

describe('search in the universe', () => {
  it('flies Enter only to results that answer what is typed now', () => {
    expect(enterTarget({ results: [7, 3], resultsFor: 'python' }, 'python ')).toBe(7);
    expect(enterTarget({ results: [7, 3], resultsFor: 'python' }, 'rust')).toBeNull(); // previous query's
    expect(enterTarget({ results: [], resultsFor: 'rust' }, 'rust')).toBeNull();
  });

  it('selects a single hit once per search, not on every refresh', () => {
    expect(shouldAutoSelect('', 'lake', 'id1')).toBe(true);
    expect(shouldAutoSelect('lake\u0000id1', 'lake', 'id1')).toBe(false);
    expect(shouldAutoSelect('lake\u0000id1', 'lake lot', 'id1')).toBe(true);
  });
});

describe('photo planet textures', () => {
  it('stay bounded, evicting the least recently shown and never one on screen', () => {
    const order = ['a', 'b', 'c', 'd', 'e'];
    expect(texturesToEvict(order, new Set(['a']), 3)).toEqual(['b', 'c']);
    expect(texturesToEvict(order, new Set(), 5)).toEqual([]);
  });
});

describe('flying to a selection', () => {
  const placed = (sceneVersion: number) =>
    useLayout.setState({
      current: {
        positions: new Float32Array([4, 5, 6]),
        galaxyCentres: new Float32Array(0),
        galaxyRadii: new Float32Array(0),
        extent: 300,
        kind: 'project',
        sceneVersion,
      },
    });

  it('waits for the layout of the current scene, then flies once per selection and layout', () => {
    const scene = { ...emptyScene(), n: 1, ids: ['a'], index: new Map([['a', 0]]) };
    useScene.setState({ scene, version: 2 });
    placed(1); // the layout still belongs to the previous scene version: the item isn't placed yet
    const flown = { current: '' };
    const flights: number[][] = [];
    const fly = () => {
      const p = itemPosition(0);
      if (p) flights.push(p.toArray());
      return p !== null;
    };
    flyOnce(flown, 'a:project', fly);
    expect(flights).toEqual([]);
    placed(2); // the matching layout arrives
    flyOnce(flown, 'a:project', fly);
    expect(flights).toEqual([[4, 5, 6]]);
    useScene.setState({ version: 3 });
    placed(3); // a data refresh publishes a new layout: the camera stays where you are
    flyOnce(flown, 'a:project', fly);
    expect(flights).toHaveLength(1);
    flyOnce(flown, null, fly); // deselected: selecting it again flies again
    flyOnce(flown, 'a:project', fly);
    expect(flights).toHaveLength(2);
  });
});

describe('the camera API', () => {
  it('goes back to its idle defaults when a scene unmounts', () => {
    rig.state = () => ({ position: [1, 2, 3], target: [4, 5, 6], flying: true, lastFlight: null });
    rig.zoom = () => ({ fraction: 0.2, galaxy: 3 });
    resetRig();
    expect(rig.state()).toEqual({ position: [0, 0, 0], target: [0, 0, 0], flying: false, lastFlight: null });
    expect(rig.zoom()).toEqual({ fraction: 1, galaxy: -1 });
  });
});
