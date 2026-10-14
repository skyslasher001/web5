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

/** Which queries a Core event makes stale (the agent engine's views refresh from events, not polling). */
export function staleQueriesFor(eventType: string): string[] {
  if (eventType.startsWith('approval.')) return ['approvals', 'engine', 'tasks', 'task', 'audit'];
  if (eventType.startsWith('killswitch.')) return ['engine', 'approvals', 'tasks', 'task', 'audit'];
  if (eventType === 'agent.step') return ['task'];
  if (eventType.startsWith('agent.')) return ['tasks', 'task', 'budget', 'audit', 'roster', 'forge'];
  if (eventType.startsWith('memory.')) return ['memories'];
  if (eventType.startsWith('budget.')) return ['budget'];
  if (eventType.startsWith('permission.')) return ['rules'];
  if (eventType.startsWith('mcp.')) return ['mcp', 'engine'];
  if (eventType.startsWith('forge.') || eventType === 'error.raised') return ['forge'];
  return [];
}

const ENGINE_REFRESH_MS = 250;
const pendingKeys = new Set<string>();
let engineRefresh: ReturnType<typeof setTimeout> | null = null;

/** Refetch the agent-engine queries an event touches, batching bursts (a task emits many steps). */
export function refreshForEvent(eventType: string): void {
  const keys = staleQueriesFor(eventType);
  if (keys.length === 0) return;
  keys.forEach((k) => pendingKeys.add(k));
  if (engineRefresh !== null) return;
  engineRefresh = setTimeout(() => {
    engineRefresh = null;
    const due = new Set(pendingKeys);
    pendingKeys.clear();
    void queryClient.invalidateQueries({ predicate: (q) => due.has(String(q.queryKey[0])) });
  }, ENGINE_REFRESH_MS);
}
