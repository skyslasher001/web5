// Constellation results (ARCHITECTURE.md §6.4): a search in the universe view highlights its results,
// numbers the first nine, and the camera flies to frame them. One clear result is flown to and selected.
import { useEffect } from 'react';
import { useSearch } from '../../lib/queries';
import { useUniverse } from '../../state/store';
import { useInteraction } from './interaction';
import { useScene } from './sceneData';

export const MAX_RESULTS = 100;

export function resultIndices(ids: string[], index: Map<string, number>, max = MAX_RESULTS): number[] {
  const out: number[] = [];
  for (const id of ids) {
    const i = index.get(id);
    if (i !== undefined) out.push(i);
    if (out.length >= max) break;
  }
  return out;
}

export function useConstellation(): void {
  const view = useUniverse((s) => s.view);
  const query = useUniverse((s) => s.query.trim());
  const { search, searching } = useSearch();
  const version = useScene((s) => s.version);
  useEffect(() => {
    const set = useInteraction.getState().setResults;
    if (view !== 'universe' || !query || !searching || !search.data) {
      set([]);
      return;
    }
    const indices = resultIndices(
      search.data.hits.map((h) => h.item.id),
      useScene.getState().scene.index,
    );
    set(indices);
    if (search.data.hits.length === 1 && search.data.hits[0]) {
      useUniverse.getState().selectItem(search.data.hits[0].item.id);
    }
  }, [view, query, searching, search.data, version]);
}
