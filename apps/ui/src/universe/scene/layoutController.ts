// Keeps the current layout's positions up to date: asks the worker for Project / Time / Graph and Core for
// Semantic, caches each per scene version, and falls back to Project (saying why) while Semantic computes.
import { create } from 'zustand';
import type { CoreApi } from '../../lib/api';
import type { Layout } from '../../state/store';
import { mergeSemantic, type LayoutResult } from './layouts';
import type { LayoutKind, LayoutRequest, LayoutResponse } from './layout.worker';
import { layoutInput, type SceneData } from './sceneData';

export interface PlacedLayout extends LayoutResult {
  kind: Layout;
  sceneVersion: number;
}

interface LayoutState {
  current: PlacedLayout | null;
  /** A layout is being computed (the previous one stays on screen meanwhile). */
  computing: Layout | null;
  /** Why the shown layout isn't the one you picked, e.g. Semantic still arranging. */
  notice: string | null;
}

export const useLayout = create<LayoutState>()(() => ({ current: null, computing: null, notice: null }));

const SEMANTIC_POLL_MS = 3000;

export class LayoutController {
  private worker: Worker | null = null;
  private nextId = 1;
  private pending = new Map<number, (r: LayoutResponse) => void>();
  private cache = new Map<string, PlacedLayout>();
  private wanted: { kind: Layout; scene: SceneData; version: number } | null = null;
  private poll: ReturnType<typeof setTimeout> | null = null;
  // At most one worker computation in flight; while it runs, only the newest request waits (an import can
  // bump the scene every second or two, and a Graph layout at 50k takes seconds).
  private running = false;
  private next: { kind: LayoutKind; scene: SceneData; version: number } | null = null;

  constructor(private readonly api: CoreApi) {}

  private ensureWorker(): Worker {
    if (!this.worker) {
      this.worker = new Worker(new URL('./layout.worker.ts', import.meta.url), { type: 'module' });
      this.worker.onmessage = (event: MessageEvent<LayoutResponse>) => {
        this.pending.get(event.data.id)?.(event.data);
        this.pending.delete(event.data.id);
      };
    }
    return this.worker;
  }

  private compute(kind: LayoutKind, scene: SceneData): Promise<LayoutResponse> {
    const id = this.nextId++;
    // Typed arrays are copied (structured clone), so the scene on the main thread stays intact.
    const request: LayoutRequest = { id, kind, input: layoutInput(scene) };
    return new Promise((resolve) => {
      this.pending.set(id, resolve);
      this.ensureWorker().postMessage(request);
    });
  }

  /** Show `kind` for this scene. Results that arrive after a newer request are dropped. */
  async show(kind: Layout, scene: SceneData, version: number): Promise<void> {
    this.wanted = { kind, scene, version };
    if (this.poll) clearTimeout(this.poll);
    this.poll = null;
    const key = `${kind}:${version}`;
    const cached = this.cache.get(key);
    if (cached) {
      useLayout.setState({ current: cached, computing: null, notice: null });
      return;
    }
    if (scene.n === 0) {
      // An empty layout, not null: what was drawn before has to go (the last items were trashed).
      const empty: PlacedLayout = {
        positions: new Float32Array(0),
        galaxyCentres: new Float32Array(0),
        galaxyRadii: new Float32Array(0),
        extent: 300,
        kind,
        sceneVersion: version,
      };
      useLayout.setState({ current: empty, computing: null, notice: null });
      return;
    }
    useLayout.setState({ computing: kind });
    if (kind !== 'semantic') {
      this.next = { kind, scene, version };
      if (!this.running) void this.drain();
      return;
    }
    try {
      const semantic = await this.api.semanticLayout();
      if (semantic.status === 'ready') {
        const result = mergeSemantic(layoutInput(scene), scene.index, semantic.ids, semantic.positions);
        this.accept(
          'semantic',
          version,
          result,
          semantic.stale ? 'Semantic: updating with new items…' : null,
        );
        return;
      }
      // Not ready: show the Project layout meanwhile, and say why.
      const fallback = await this.projectFor(scene, version);
      if (!this.isWanted('semantic', version)) return;
      useLayout.setState({
        current: fallback, // the same object on every poll, so nothing downstream rebuilds
        computing: semantic.status === 'computing' ? 'semantic' : null,
        notice: semantic.reason ?? 'The Semantic layout is not available yet.',
      });
      if (semantic.status === 'computing') {
        this.poll = setTimeout(() => void this.show('semantic', scene, version), SEMANTIC_POLL_MS);
      }
    } catch (err) {
      useLayout.setState({
        computing: null,
        notice: `Semantic layout failed to load: ${err instanceof Error ? err.message : String(err)}`,
      });
    }
  }

  private async drain(): Promise<void> {
    this.running = true;
    try {
      while (this.next) {
        const job = this.next;
        this.next = null;
        if (!this.isWanted(job.kind, job.version)) continue; // superseded while it waited
        const response = await this.compute(job.kind, job.scene);
        this.accept(job.kind, job.version, response.result, null);
      }
    } finally {
      this.running = false;
    }
  }

  /** Core finished a Semantic layout (`layout.updated`): drop the cached one so it's fetched again. */
  semanticUpdated(): void {
    for (const key of [...this.cache.keys()]) if (key.startsWith('semantic:')) this.cache.delete(key);
    if (this.wanted?.kind === 'semantic') void this.show('semantic', this.wanted.scene, this.wanted.version);
  }

  private async projectFor(scene: SceneData, version: number): Promise<PlacedLayout> {
    const key = `project:${version}`;
    const cached = this.cache.get(key);
    if (cached) return cached;
    const response = await this.compute('project', scene);
    const placed: PlacedLayout = { ...response.result, kind: 'project', sceneVersion: version };
    this.remember(key, placed);
    return placed;
  }

  private isWanted(kind: Layout, version: number): boolean {
    return this.wanted?.kind === kind && this.wanted.version === version;
  }

  private accept(kind: Layout, version: number, result: LayoutResult, notice: string | null): void {
    const placed: PlacedLayout = { ...result, kind, sceneVersion: version };
    this.remember(`${kind}:${version}`, placed);
    if (!this.isWanted(kind, version)) return;
    useLayout.setState({ current: placed, computing: null, notice });
  }

  private remember(key: string, placed: PlacedLayout): void {
    this.cache.set(key, placed);
    // Keep only the newest scene version's layouts.
    for (const k of [...this.cache.keys()]) {
      if (!k.endsWith(`:${placed.sceneVersion}`)) this.cache.delete(k);
    }
  }

  dispose(): void {
    if (this.poll) clearTimeout(this.poll);
    this.worker?.terminate();
    this.worker = null;
  }
}
