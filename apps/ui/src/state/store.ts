import type { AgentInfo, BridgeConfig, CoreEvent, DesktopState, ItemType } from '@universe/shared-types';
import { create } from 'zustand';
import type { ItemSort } from '../lib/api';
import type { ConnectionState } from '../lib/socket';
import {
  applyAgentEvent,
  applyChatEvent,
  describeEvent,
  type ActivityItem,
  type AgentActivity,
  type ChatMessage,
} from './reducers';

export type Panel = 'context' | 'system' | 'vault';
export type View = 'universe' | 'grid' | 'list';

/** Events that change what the 2D views show. Bursts (an import of 500 files) refresh once. */
const ITEM_EVENT = /^(item|pipeline)\./;
const ITEMS_REFRESH_MS = 800;
let itemsRefresh: ReturnType<typeof setTimeout> | null = null;

interface UniverseState {
  config: BridgeConfig | null;
  desktop: DesktopState | null;
  connection: ConnectionState;
  reconnectAttempt: number;
  lastSeq: number;
  activity: ActivityItem[];
  agents: AgentInfo[];
  agentActivity: Record<string, AgentActivity>;
  conversationId: string | null;
  messages: ChatMessage[];
  selectedProjectId: string | null;
  chatOpen: boolean;
  paletteOpen: boolean;
  panel: Panel;
  zen: boolean;
  /** Bumped by events that should refetch server data (projects, models). */
  dataVersion: number;
  view: View;
  selectedItemId: string | null;
  query: string;
  typeFilter: ItemType[];
  sort: ItemSort;
  showTrash: boolean;
  /** Bumped (throttled) by item and pipeline events so item lists refetch. */
  itemsVersion: number;
  searchFocusTick: number;
  /** Bumped when the keyboard should move from the search field to the results. */
  resultsFocusTick: number;

  setConfig(config: BridgeConfig): void;
  setDesktop(desktop: DesktopState): void;
  setConnection(state: ConnectionState, attempt: number): void;
  setAgents(agents: AgentInfo[]): void;
  applyEvent(event: CoreEvent): void;
  seedActivity(events: CoreEvent[], lastSeq: number): void;
  openConversation(id: string, messages: ChatMessage[]): void;
  newConversation(): string;
  selectProject(id: string | null): void;
  setChatOpen(open: boolean): void;
  setPaletteOpen(open: boolean): void;
  setPanel(panel: Panel): void;
  toggleZen(): void;
  addNotice(tone: ActivityItem['tone'], text: string): void;
  setView(view: View): void;
  selectItem(id: string | null): void;
  setQuery(query: string): void;
  setTypeFilter(types: ItemType[]): void;
  setSort(sort: ItemSort): void;
  setShowTrash(show: boolean): void;
  refreshItems(): void;
  focusSearch(): void;
  focusResults(): void;
}

const ACTIVITY_LIMIT = 40;
const REFRESH_TYPES = new Set([
  'project.created',
  'project.updated',
  'model.assignment_changed',
  'service.started',
]);

function activityFrom(events: CoreEvent[]): ActivityItem[] {
  return events
    .map((e) => {
      const line = describeEvent(e);
      return line ? { id: e.id, ts: e.ts, ...line } : null;
    })
    .filter((x): x is ActivityItem => x !== null)
    .reverse()
    .slice(0, ACTIVITY_LIMIT);
}

export const useUniverse = create<UniverseState>()((set, get) => ({
  config: null,
  desktop: null,
  connection: 'connecting',
  reconnectAttempt: 0,
  lastSeq: 0,
  activity: [],
  agents: [],
  agentActivity: {},
  conversationId: null,
  messages: [],
  selectedProjectId: null,
  chatOpen: false,
  paletteOpen: false,
  panel: 'context',
  zen: false,
  dataVersion: 0,
  view: 'universe',
  selectedItemId: null,
  query: '',
  typeFilter: [],
  sort: 'added',
  showTrash: false,
  itemsVersion: 0,
  searchFocusTick: 0,
  resultsFocusTick: 0,

  setConfig: (config) => set({ config }),
  setDesktop: (desktop) => set({ desktop }),
  setConnection: (connection, reconnectAttempt) => set({ connection, reconnectAttempt }),
  setAgents: (agents) => set({ agents }),
  applyEvent: (event) => {
    if (ITEM_EVENT.test(event.type) && itemsRefresh === null) {
      itemsRefresh = setTimeout(() => {
        itemsRefresh = null;
        get().refreshItems();
      }, ITEMS_REFRESH_MS);
    }
    set((s) => {
      const chat = applyChatEvent({ conversationId: s.conversationId, messages: s.messages }, event);
      const line = describeEvent(event);
      return {
        lastSeq: event.seq != null ? Math.max(s.lastSeq, event.seq) : s.lastSeq,
        messages: chat.messages,
        agentActivity: applyAgentEvent(s.agentActivity, event),
        activity: line
          ? [{ id: event.id, ts: event.ts, ...line }, ...s.activity].slice(0, ACTIVITY_LIMIT)
          : s.activity,
        dataVersion: REFRESH_TYPES.has(event.type) ? s.dataVersion + 1 : s.dataVersion,
        selectedItemId:
          event.type === 'item.deleted' && event.subject_id === s.selectedItemId ? null : s.selectedItemId,
      };
    });
  },
  seedActivity: (events, lastSeq) =>
    set({ activity: activityFrom(events), lastSeq: Math.max(get().lastSeq, lastSeq) }),
  openConversation: (conversationId, messages) => set({ conversationId, messages, chatOpen: true }),
  newConversation: () => {
    const id = crypto.randomUUID();
    set({ conversationId: id, messages: [], chatOpen: true });
    return id;
  },
  selectProject: (selectedProjectId) => set({ selectedProjectId, selectedItemId: null, panel: 'context' }),
  setChatOpen: (chatOpen) => set({ chatOpen }),
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setPanel: (panel) => set({ panel }),
  toggleZen: () => set((s) => ({ zen: !s.zen, paletteOpen: false })),
  addNotice: (tone, text) =>
    set((s) => ({
      activity: [
        { id: `local-${crypto.randomUUID()}`, ts: new Date().toISOString(), tone, text },
        ...s.activity,
      ].slice(0, ACTIVITY_LIMIT),
    })),
  setView: (view) => set({ view }),
  selectItem: (selectedItemId) => set({ selectedItemId, panel: 'context' }),
  setQuery: (query) => set((s) => ({ query, view: query && s.view === 'universe' ? 'list' : s.view })),
  setTypeFilter: (typeFilter) => set({ typeFilter }),
  setSort: (sort) => set({ sort }),
  setShowTrash: (showTrash) => set({ showTrash, selectedItemId: null }),
  refreshItems: () => set((s) => ({ itemsVersion: s.itemsVersion + 1 })),
  focusSearch: () => set((s) => ({ searchFocusTick: s.searchFocusTick + 1 })),
  focusResults: () =>
    set((s) => ({ resultsFocusTick: s.resultsFocusTick + 1, view: s.view === 'universe' ? 'list' : s.view })),
}));
