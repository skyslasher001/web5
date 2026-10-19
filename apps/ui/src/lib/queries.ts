import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query';
import type { ItemPage } from '@universe/shared-types';
import { useEffect, useState } from 'react';
import { useUniverse } from '../state/store';
import { useApi } from './api-context';

export function useProjects() {
  const api = useApi();
  const version = useUniverse((s) => s.dataVersion);
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['projects', version],
    queryFn: api.projects,
    enabled: online,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useModels() {
  const api = useApi();
  const version = useUniverse((s) => s.dataVersion);
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['models', version],
    queryFn: api.models,
    enabled: online,
    refetchInterval: 15_000,
  });
}

export function useVitals(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['vitals'],
    queryFn: api.vitals,
    enabled: enabled && online,
    refetchInterval: 3_000,
  });
}

export function useHardware(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['hardware'],
    queryFn: api.hardware,
    enabled: enabled && online,
    staleTime: Infinity,
  });
}

export function useRecommendation(enabled: boolean) {
  const api = useApi();
  const version = useUniverse((s) => s.dataVersion);
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['recommendation', version],
    queryFn: api.recommendation,
    enabled: enabled && online,
  });
}

// ---------- vault ----------

export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

/** Search results for the query in the top bar (shared by the 2D views and the universe's constellation). */
export function useSearch() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  const query = useDebounced(
    useUniverse((s) => s.query.trim()),
    160,
  );
  const types = useUniverse((s) => s.typeFilter);
  const project = useUniverse((s) => s.selectedProjectId);
  const trashed = useUniverse((s) => s.showTrash);
  const search = useQuery({
    queryKey: ['search', query, types, project],
    queryFn: () => api.search({ q: query, types, project, limit: 100 }),
    enabled: online && query.length > 0 && !trashed,
    placeholderData: keepPreviousData,
  });
  return { search, query, searching: query.length > 0 && !trashed };
}

/** The current 2D view's items: search results when there's a query, otherwise a paged listing. */
export function useItemsView() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  const types = useUniverse((s) => s.typeFilter);
  const project = useUniverse((s) => s.selectedProjectId);
  const sort = useUniverse((s) => s.sort);
  const trashed = useUniverse((s) => s.showTrash);
  const { search, query } = useSearch();
  const listing = useInfiniteQuery({
    queryKey: ['items', types, project, sort, trashed],
    queryFn: ({ pageParam }) => api.items({ types, project, sort, trashed, cursor: pageParam, limit: 200 }),
    initialPageParam: null as string | null,
    getNextPageParam: (last: ItemPage) => last.next_cursor ?? undefined,
    enabled: online && (query.length === 0 || trashed),
    placeholderData: keepPreviousData,
  });
  const searching = query.length > 0 && !trashed;
  const listed = listing.data?.pages.flatMap((p) => p.items) ?? [];
  return {
    searching,
    search,
    listing,
    /** Everything that matches (the list loads it page by page as you scroll). */
    total: searching ? (search.data?.hits.length ?? 0) : (listing.data?.pages[0]?.total ?? listed.length),
    items: searching ? (search.data?.hits.map((h) => h.item) ?? []) : listed,
  };
}

export function useItem(id: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ['item', id],
    queryFn: () => api.item(id as string),
    enabled: !!id,
    placeholderData: keepPreviousData,
  });
}

export function useQueueStats() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({ queryKey: ['queue'], queryFn: api.jobStats, enabled: online, refetchInterval: 3_000 });
}

export function useVaultInfo(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['vault-info'],
    queryFn: api.vaultInfo,
    enabled: enabled && online,
    placeholderData: keepPreviousData,
  });
}

/** An object URL for an item's thumbnail, fetched with the session token (an <img src> can't send it).
 * The URL lives in the query cache; main.tsx revokes it when the entry is garbage-collected. */
export function useThumbnail(id: string, enabled: boolean): string | null {
  const api = useApi();
  const query = useQuery({
    queryKey: ['thumb', id],
    queryFn: async () => URL.createObjectURL(await api.thumbnail(id)),
    enabled,
    staleTime: Infinity,
    gcTime: 5 * 60_000,
    retry: false,
  });
  return query.data ?? null;
}

// ---------- agent engine ----------

export function useEngine() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({ queryKey: ['engine'], queryFn: api.engine, enabled: online, refetchInterval: 30_000 });
}

/** Forge: what's installed, the open issues and the proposals. Forge and agent events refresh them. */
export function useForgeStatus() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({ queryKey: ['forge', 'status'], queryFn: api.forgeStatus, enabled: online });
}

export function useForgeIssues() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({ queryKey: ['forge', 'issues'], queryFn: api.forgeIssues, enabled: online });
}

export function useForgeProposals() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({ queryKey: ['forge', 'proposals'], queryFn: api.forgeProposals, enabled: online });
}

/** Research (Phase 6): watched topics/pages and the "sent where" privacy log. */
export function useWatchlists() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['research', 'watchlists'],
    queryFn: api.watchlists,
    enabled: online,
    refetchInterval: 60_000,
  });
}

export function useSentRequests(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['research', 'requests'],
    queryFn: api.sentRequests,
    enabled: enabled && online,
    refetchInterval: 30_000,
  });
}

/** Grouped errors from every service (System → Vitals). New errors refresh it. */
export function useErrors(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['errors'],
    queryFn: api.errors,
    enabled: enabled && online,
    refetchInterval: 60_000,
  });
}

export function useBackupStatus(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['backups'],
    queryFn: api.backupStatus,
    enabled: enabled && online,
    refetchInterval: 30_000,
  });
}

/** Every agent with its synopsis and stats (the Agents panel's roster). Agent events refresh it. */
export function useAgentRoster() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({ queryKey: ['roster'], queryFn: api.agentRoster, enabled: online });
}

/** Top-level tasks (not specialists' sub-tasks), newest first. Events refresh it (refreshForEvent). */
export function useTasks() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.tasks({ limit: 50 }),
    enabled: online,
    placeholderData: keepPreviousData,
  });
}

export function useTask(id: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ['task', id],
    queryFn: () => api.task(id as string),
    enabled: !!id,
    placeholderData: keepPreviousData,
  });
}

export function useApprovals() {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['approvals'],
    queryFn: api.approvals,
    enabled: online,
    refetchInterval: 60_000,
  });
}

export function useMemories(status?: 'active' | 'proposed') {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['memories', status ?? 'all'],
    queryFn: () => api.memories(status),
    enabled: online,
    placeholderData: keepPreviousData,
  });
}

// These need the protected policy engine; without it Core answers 503, so don't retry.
export function usePermissionRules(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['rules'],
    queryFn: api.permissionRules,
    enabled: enabled && online,
    retry: false,
  });
}

export function useBudget(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['budget'],
    queryFn: api.budget,
    enabled: enabled && online,
    retry: false,
    refetchInterval: 60_000,
  });
}

export function useAudit(enabled: boolean, limit = 50) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['audit', limit],
    queryFn: () => api.audit(limit),
    enabled: enabled && online,
    placeholderData: keepPreviousData,
  });
}

export function useMcpServers(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({ queryKey: ['mcp'], queryFn: api.mcpServers, enabled: enabled && online });
}

/** Voice (Phase 7): the process, settings and models. Voice events refresh it (refreshForEvent). */
export function useVoiceStatus(enabled = true) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({ queryKey: ['voice', 'status'], queryFn: api.voiceStatus, enabled: online && enabled });
}

export function useVoices(enabled = true) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({ queryKey: ['voice', 'voices'], queryFn: api.voices, enabled: online && enabled });
}
