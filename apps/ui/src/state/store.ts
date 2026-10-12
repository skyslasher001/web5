import type { AgentInfo, BridgeConfig, CoreEvent, DesktopState } from '@universe/shared-types';
import { create } from 'zustand';
import type { ConnectionState } from '../lib/socket';
import {
  applyAgentEvent,
  applyChatEvent,
  describeEvent,
  type ActivityItem,
  type AgentActivity,
  type ChatMessage,
} from './reducers';

export type Panel = 'context' | 'system';

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

  setConfig: (config) => set({ config }),
  setDesktop: (desktop) => set({ desktop }),
  setConnection: (connection, reconnectAttempt) => set({ connection, reconnectAttempt }),
  setAgents: (agents) => set({ agents }),
  applyEvent: (event) =>
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
      };
    }),
  seedActivity: (events, lastSeq) =>
    set({ activity: activityFrom(events), lastSeq: Math.max(get().lastSeq, lastSeq) }),
  openConversation: (conversationId, messages) => set({ conversationId, messages, chatOpen: true }),
  newConversation: () => {
    const id = crypto.randomUUID();
    set({ conversationId: id, messages: [], chatOpen: true });
    return id;
  },
  selectProject: (selectedProjectId) => set({ selectedProjectId, panel: 'context' }),
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
}));
