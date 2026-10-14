// Constellation results (ARCHITECTURE.md §6.4): a search in the universe view highlights its results,
// numbers the first nine, and the camera flies to frame them. One clear result is flown to and selected.
import { useEffect, useRef } from 'react';
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

/** Select a search's single hit once per search (query + hit), not on every refresh. */
export function shouldAutoSelect(last: string, query: string, hit: string): boolean {
  return last !== `${query}\u0000${hit}`;
}

export function useConstellation(): void {
  const view = useUniverse((s) => s.view);
  const query = useUniverse((s) => s.query.trim());
  const { search, searching, query: asked } = useSearch();
  const version = useScene((s) => s.version);
  // The search whose single hit was selected: a data refresh or a re-fetch of the same search must not
  // select it again (it would undo Esc or a click elsewhere and fly the camera back).
  const autoSelected = useRef('');
  useEffect(() => {
    const { setResults, pendingFly, setPendingFly } = useInteraction.getState();
    if (view !== 'universe' || !query || !searching || !search.data) {
      setResults([]);
      return;
    }
    const scene = useScene.getState().scene;
    const indices = resultIndices(
      search.data.hits.map((h) => h.item.id),
      scene.index,
    );
    // Results kept from the previous query while this one loads answer that query, not this one.
    const fresh = !search.isPlaceholderData && asked === query;
    setResults(indices, fresh ? query : '');
    if (fresh && pendingFly === query) {
      setPendingFly(null);
      if (indices.length) useUniverse.getState().selectItem(scene.ids[indices[0]!]!);
    }
    const only = search.data.hits.length === 1 ? search.data.hits[0]?.item.id : undefined;
    if (fresh && only && shouldAutoSelect(autoSelected.current, query, only)) {
      autoSelected.current = `${query}\u0000${only}`;
      useUniverse.getState().selectItem(only);
    }
  }, [view, query, asked, searching, search.data, search.isPlaceholderData, version]);
}
