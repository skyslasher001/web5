// The one query cache, shared by React (main.tsx) and the store (which refreshes item queries in place).
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

// Thumbnails are object URLs held in the cache: free each one when its entry is dropped.
queryClient.getQueryCache().subscribe((event) => {
  const { queryKey, state } = event.query;
  if (event.type === 'removed' && queryKey[0] === 'thumb' && typeof state.data === 'string') {
    URL.revokeObjectURL(state.data);
  }
});

/** Queries whose results change when items do. */
const ITEM_QUERIES = new Set(['projects', 'items', 'search', 'item', 'vault-info']);

/** Refetch what's on screen in place: an infinite list keeps its loaded pages, so nothing jumps while you scroll. */
export function refreshItemQueries(): Promise<void> {
  return queryClient.invalidateQueries({ predicate: (q) => ITEM_QUERIES.has(String(q.queryKey[0])) });
}
