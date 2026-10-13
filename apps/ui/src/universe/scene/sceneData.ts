// Everything the universe draws, as typed arrays (ADR-0012): loaded page by page from GET /universe/items,
// refreshed incrementally after item events. React only sees a version number, never 50k objects.
import type { components, CoreEvent } from '@universe/shared-types';
import { create } from 'zustand';
import type { CoreApi } from '../../lib/api';
import { fnv1a, type LayoutInput } from './layouts';
import { IDEA_STAGES, TYPE_CODE } from './types';

type UniverseItems = components['schemas']['UniverseItems'];

export interface SceneRow {
  id: string;
  type: string;
  title: string;
  galaxy: string | null;
  created: number;
  captured: number;
  opened: number;
  opens: number;
  status: string;
  ideaStage: string | null;
  pinned: boolean;
}

export interface SceneData {
  n: number;
  ids: string[];
  index: Map<string, number>;
  titles: string[];
  typeNames: string[];
  types: Uint8Array;
  ideaStages: (string | null)[];
  galaxyIds: string[]; // galaxy index → project id
  galaxy: Int16Array;
  created: Float64Array;
  opened: Float64Array;
  opens: Uint16Array;
  pinned: Uint8Array;
  comet: Uint8Array;
  hashes: Uint32Array;
  linksA: Uint32Array;
  linksB: Uint32Array;
  linkSuggested: Uint8Array;
}

/** Inbox captures without a galaxy from the last week arrive as comets at the edge (SPEC §7). */
export const COMET_DAYS = 7;

export function emptyScene(): SceneData {
  return {
    n: 0,
    ids: [],
    index: new Map(),
    titles: [],
    typeNames: [],
    types: new Uint8Array(0),
    ideaStages: [],
    galaxyIds: [],
    galaxy: new Int16Array(0),
    created: new Float64Array(0),
    opened: new Float64Array(0),
    opens: new Uint16Array(0),
    pinned: new Uint8Array(0),
    comet: new Uint8Array(0),
    hashes: new Uint32Array(0),
    linksA: new Uint32Array(0),
    linksB: new Uint32Array(0),
    linkSuggested: new Uint8Array(0),
  };
}

interface LinkRows {
  sources: string[];
  targets: string[];
  states: string[];
}

/** Build the typed arrays from rows (≈10 ms at 50k). `galaxyOrder` is the projects' display order. */
export function buildScene(
  rows: Iterable<SceneRow>,
  links: LinkRows,
  galaxyOrder: string[],
  now = Date.now() / 1000,
): SceneData {
  const list = [...rows].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const n = list.length;
  const scene = emptyScene();
  const galaxyIndex = new Map(galaxyOrder.map((id, i) => [id, i]));
  scene.n = n;
  scene.galaxyIds = [...galaxyOrder];
  scene.types = new Uint8Array(n);
  scene.galaxy = new Int16Array(n);
  scene.created = new Float64Array(n);
  scene.opened = new Float64Array(n);
  scene.opens = new Uint16Array(n);
  scene.pinned = new Uint8Array(n);
  scene.comet = new Uint8Array(n);
  scene.hashes = new Uint32Array(n);
  list.forEach((r, i) => {
    scene.ids.push(r.id);
    scene.index.set(r.id, i);
    scene.titles.push(r.title);
    scene.typeNames.push(r.type);
    scene.ideaStages.push(r.ideaStage);
    scene.types[i] = TYPE_CODE.get(r.type) ?? 0;
    let g = r.galaxy ? (galaxyIndex.get(r.galaxy) ?? -1) : -1;
    if (r.galaxy && g < 0) {
      // A galaxy the project list doesn't have yet (just created): give it a slot at the end.
      g = scene.galaxyIds.length;
      galaxyIndex.set(r.galaxy, g);
      scene.galaxyIds.push(r.galaxy);
    }
    scene.galaxy[i] = g;
    scene.created[i] = r.created;
    scene.opened[i] = r.opened;
    scene.opens[i] = Math.min(r.opens, 65535);
    scene.pinned[i] = r.pinned ? 1 : 0;
    scene.comet[i] = g < 0 && r.status === 'inbox' && now - r.created < COMET_DAYS * 86400 ? 1 : 0;
    scene.hashes[i] = fnv1a(r.id);
  });
  const a: number[] = [];
  const b: number[] = [];
  const suggested: number[] = [];
  links.sources.forEach((source, k) => {
    const i = scene.index.get(source);
    const j = scene.index.get(links.targets[k]!);
    if (i === undefined || j === undefined) return;
    a.push(i);
    b.push(j);
    suggested.push(links.states[k] === 'suggested' ? 1 : 0);
  });
  scene.linksA = new Uint32Array(a);
  scene.linksB = new Uint32Array(b);
  scene.linkSuggested = new Uint8Array(suggested);
  return scene;
}

export function layoutInput(scene: SceneData): LayoutInput {
  return {
    n: scene.n,
    hashes: scene.hashes,
    galaxy: scene.galaxy,
    created: scene.created,
    comet: scene.comet,
    galaxyCount: scene.galaxyIds.length,
    linksA: scene.linksA,
    linksB: scene.linksB,
  };
}

/** Idea stage code for the shader (0 = not an idea). */
export function ideaStageCode(stage: string | null): number {
  return Math.max(0, IDEA_STAGES.indexOf((stage ?? '') as (typeof IDEA_STAGES)[number]));
}

function rowsOf(page: UniverseItems): SceneRow[] {
  return page.ids.map((id, k) => ({
    id,
    type: page.types[k]!,
    title: page.titles[k]!,
    galaxy: page.galaxies[k] ?? null,
    created: page.created[k]!,
    captured: page.captured[k]!,
    opened: page.opened[k]!,
    opens: page.opens[k]!,
    status: page.statuses[k]!,
    ideaStage: page.idea_stages[k] ?? null,
    pinned: page.pinned[k]!,
  }));
}

interface SceneState {
  scene: SceneData;
  /** Bumped whenever `scene` changes (layouts and buffers rebuild on it). */
  version: number;
  loading: boolean;
  loaded: number;
  total: number;
  error: string | null;
}

export const useScene = create<SceneState>()(() => ({
  scene: emptyScene(),
  version: 0,
  loading: false,
  loaded: 0,
  total: 0,
  error: null,
}));

/** Loads and keeps the scene current. One per app; the universe view starts it. */
export class SceneLoader {
  private rows = new Map<string, SceneRow>();
  private links: LinkRows = { sources: [], targets: [], states: [] };
  private since: string | null = null;
  private galaxyOrder: string[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private dirtyItems = false;
  private dirtyLinks = false;
  private busy = false;

  constructor(private readonly api: CoreApi) {}

  setGalaxyOrder(ids: string[]): void {
    if (ids.join() === this.galaxyOrder.join()) return;
    this.galaxyOrder = ids;
    if (this.rows.size) this.publish();
  }

  /** Full load, showing the first page as soon as it arrives (progressive streaming). */
  async load(): Promise<void> {
    useScene.setState({ loading: true, error: null });
    try {
      let cursor: string | null = null;
      this.rows.clear();
      const linksPromise = this.api.universeLinks();
      do {
        const page: UniverseItems = await this.api.universeItems({ cursor });
        for (const row of rowsOf(page)) this.rows.set(row.id, row);
        this.since ??= page.server_time;
        cursor = page.next_cursor ?? null;
        useScene.setState({ loaded: this.rows.size, total: page.total });
        if (!cursor) this.links = await linksPromise;
        this.publish();
      } while (cursor);
    } catch (err) {
      useScene.setState({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      useScene.setState({ loading: false });
    }
  }

  /** Called for every Core event; bursts are coalesced into one incremental refresh. */
  onEvent(event: CoreEvent): void {
    if (/^(item\.|pipeline\.stage\.completed)/.test(event.type)) this.dirtyItems = true;
    if (/^(link\.|item\.processed|item\.deleted|item\.trashed)/.test(event.type)) this.dirtyLinks = true;
    if ((this.dirtyItems || this.dirtyLinks) && this.timer === null) {
      this.timer = setTimeout(() => {
        this.timer = null;
        void this.refresh();
      }, 1200);
    }
  }

  private async refresh(): Promise<void> {
    if (this.busy || this.since === null) return;
    this.busy = true;
    const items = this.dirtyItems;
    const links = this.dirtyLinks;
    this.dirtyItems = this.dirtyLinks = false;
    try {
      if (items) {
        let cursor: string | null = null;
        let next = this.since;
        do {
          const page: UniverseItems = await this.api.universeItems({ cursor, since: this.since });
          for (const id of page.removed) this.rows.delete(id);
          for (const row of rowsOf(page)) this.rows.set(row.id, row);
          next = page.server_time;
          cursor = page.next_cursor ?? null;
          useScene.setState({ total: page.total });
        } while (cursor);
        this.since = next;
      }
      if (links) this.links = await this.api.universeLinks();
      this.publish();
    } catch {
      // Core restarting: the next event (or reconnect) tries again.
      this.dirtyItems ||= items;
      this.dirtyLinks ||= links;
    } finally {
      this.busy = false;
    }
  }

  private publish(): void {
    const scene = buildScene(this.rows.values(), this.links, this.galaxyOrder);
    useScene.setState((s) => ({ scene, version: s.version + 1, loaded: scene.n }));
  }
}
