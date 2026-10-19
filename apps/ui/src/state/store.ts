import type {
  AgentInfo,
  BridgeConfig,
  CoreEvent,
  DesktopState,
  ItemType,
  KillSwitchState,
} from '@universe/shared-types';
import { create } from 'zustand';
import type { ItemSort } from '../lib/api';
import {
  detectQuality,
  loadQualitySetting,
  QUALITY_LABEL,
  saveQualitySetting,
  stepDown,
  webglRenderer,
  type Quality,
  type QualitySetting,
} from '../universe/quality';
import { refreshForEvent, refreshItemQueries } from '../lib/queryClient';
import type { ConnectionState } from '../lib/socket';
import {
  applyAgentEvent,
  applyChatEvent,
  applyStepEvent,
  describeEvent,
  pushActivity,
  type ActivityItem,
  type AgentActivity,
  type ChatMessage,
} from './reducers';

export type Panel = 'context' | 'vault' | 'agents' | 'research' | 'voice' | 'forge' | 'safety' | 'system';
export type View = 'universe' | 'grid' | 'list';
export type Layout = 'project' | 'semantic' | 'time' | 'graph';
export const LAYOUTS: Layout[] = ['project', 'semantic', 'time', 'graph'];

/** What an agent's probe is flying to (from `agent.step` targets). */
export interface ProbeTarget {
  kind: 'item' | 'project';
  id: string;
}

/** Events that change what the 2D views show. Bursts (an import of 500 files) refresh once. */
const ITEM_EVENT = /^(item|pipeline)\./;
const ITEMS_REFRESH_MS = 800;
let itemsRefresh: ReturnType<typeof setTimeout> | null = null;

/** Non-React consumers of Core events (the universe's scene loader). Returns an unsubscribe function. */
const eventListeners = new Set<(event: CoreEvent) => void>();
export function onCoreEvent(listener: (event: CoreEvent) => void): () => void {
  eventListeners.add(listener);
  return () => eventListeners.delete(listener);
}

interface UniverseState {
  config: BridgeConfig | null;
  desktop: DesktopState | null;
  connection: ConnectionState;
  reconnectAttempt: number;
  lastSeq: number;
  activity: ActivityItem[];
  agents: AgentInfo[];
  agentActivity: Record<string, AgentActivity>;
  /** What each busy agent is doing, in words, from its latest step. */
  agentSteps: Record<string, string>;
  /** The agent the Agents panel runs tasks with, and the task whose trace it shows. */
  runAgentId: string;
  selectedTaskId: string | null;
  /** The Forge proposal to show open in the Forge panel (from the approvals tray). */
  forgeFocus: string | null;
  /** From Electron main: `available` is false until the protected kill-switch control is installed. */
  killSwitch: KillSwitchState;
  /** The universe's arrangement (keys 1–4) and the time slider (epoch seconds; null = now). */
  layout: Layout;
  timeCut: number | null;
  /** The item whose viewer is open (Item zoom level), or the galaxy whose dashboard is. */
  viewerItemId: string | null;
  dashboardProjectId: string | null;
  /** A note in the viewer has unsaved edits: closing asks first. */
  viewerDirty: boolean;
  /** Bumped to fly the camera home to the Core (H). */
  homeTick: number;
  agentTargets: Record<string, ProbeTarget>;
  /** Your quality choice ('auto' by default) and what's in effect (null until the hardware is checked). */
  qualitySetting: QualitySetting;
  quality: Quality | null;
  /** Accessibility (SPEC §7): text size multiplier and the high-contrast theme. */
  textScale: number;
  highContrast: boolean;
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
  searchFocusTick: number;
  /** Bumped when the keyboard should move from the search field to the results. */
  resultsFocusTick: number;
  /** Smooth mode: no backdrop blur and a 1× pixel ratio, on a machine that was dropping frames. */
  smooth: boolean;
  /** Performance overlay (System → Display): live FPS, frame time and draw calls. Off by default. */
  perfHud: boolean;

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
  setSmooth(smooth: boolean): void;
  setPerfHud(on: boolean): void;
  openAgent(id: string): void;
  selectTask(id: string | null): void;
  openForge(proposalId: string | null): void;
  setKillSwitch(state: KillSwitchState): void;
  setLayout(layout: Layout): void;
  setTimeCut(cut: number | null): void;
  openViewer(id: string): void;
  closeViewer(): void;
  openDashboard(projectId: string): void;
  setViewerDirty(dirty: boolean): void;
  flyHome(): void;
  /** Esc in the universe: close the viewer, then deselect the item, then the galaxy. */
  zoomOut(): boolean;
  initQuality(webgl: boolean): void;
  setQualitySetting(setting: QualitySetting): void;
  /** The frame budget says this machine can't keep up: one preset down (only under Auto). */
  degradeQuality(): void;
  setTextScale(scale: number): void;
  setHighContrast(on: boolean): void;
}

const ACTIVITY_LIMIT = 40;
const REFRESH_TYPES = new Set([
  'project.created',
  'project.updated',
  'model.assignment_changed',
  'service.started',
]);

function activityFrom(events: CoreEvent[]): ActivityItem[] {
  let list: ActivityItem[] = [];
  for (const e of events) {
    const line = describeEvent(e);
    if (line) list = pushActivity(list, { id: e.id, ts: e.ts, ...line }, ACTIVITY_LIMIT);
  }
  return list;
}

/** True when nothing unsaved would be lost, or the owner agrees to discard it. */
export function discardOk(s: { viewerDirty: boolean }): boolean {
  return !s.viewerDirty || window.confirm('Discard the changes to this note?');
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
  agentSteps: {},
  runAgentId: 'core',
  selectedTaskId: null,
  forgeFocus: null,
  killSwitch: { available: false, engaged: false },
  layout: 'project',
  timeCut: null,
  viewerItemId: null,
  dashboardProjectId: null,
  viewerDirty: false,
  homeTick: 0,
  agentTargets: {},
  qualitySetting: loadQualitySetting(),
  quality: null,
  textScale: loadNumber('universe.textScale', 1),
  highContrast: loadNumber('universe.highContrast', 0) === 1,
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
  searchFocusTick: 0,
  resultsFocusTick: 0,
  smooth: false,
  perfHud: loadNumber('universe.perfHud', 0) === 1,

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
    refreshForEvent(event.type);
    eventListeners.forEach((listener) => listener(event));
    if (event.type === 'navigator.action') navigate(event.payload as { target?: string; value?: string });
    set((s) => {
      const chat = applyChatEvent({ conversationId: s.conversationId, messages: s.messages }, event);
      const line = describeEvent(event);
      return {
        lastSeq: event.seq != null ? Math.max(s.lastSeq, event.seq) : s.lastSeq,
        messages: chat.messages,
        agentActivity: applyAgentEvent(s.agentActivity, event),
        agentSteps: applyStepEvent(s.agentSteps, event),
        agentTargets: applyProbeTarget(s.agentTargets, event),
        killSwitch:
          event.type === 'killswitch.engaged' || event.type === 'killswitch.released'
            ? { ...s.killSwitch, engaged: event.type === 'killswitch.engaged' }
            : s.killSwitch,
        activity: line
          ? pushActivity(s.activity, { id: event.id, ts: event.ts, ...line }, ACTIVITY_LIMIT)
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
  // In the universe view a search forms a constellation of results (Phase 4); the list is one key away (L).
  setQuery: (query) => set({ query }),
  setTypeFilter: (typeFilter) => set({ typeFilter }),
  setSort: (sort) => set({ sort }),
  setShowTrash: (showTrash) => set({ showTrash, selectedItemId: null }),
  refreshItems: () => void refreshItemQueries(),
  focusSearch: () => set((s) => ({ searchFocusTick: s.searchFocusTick + 1 })),
  setSmooth: (smooth) => {
    document.documentElement.dataset.smooth = String(smooth);
    set({ smooth });
    if (smooth)
      get().addNotice('info', 'Smooth mode on: this display was dropping frames, so the glass blur is off');
  },
  setPerfHud: (perfHud) => {
    saveNumber('universe.perfHud', perfHud ? 1 : 0);
    set({ perfHud });
  },
  focusResults: () =>
    set((s) => ({ resultsFocusTick: s.resultsFocusTick + 1, view: s.view === 'universe' ? 'list' : s.view })),
  openAgent: (runAgentId) => set({ runAgentId, panel: 'agents' }),
  selectTask: (selectedTaskId) => set({ selectedTaskId, panel: 'agents' }),
  openForge: (forgeFocus) => set({ forgeFocus, panel: 'forge' }),
  setKillSwitch: (killSwitch) => set({ killSwitch }),
  // The time-travel slider only exists in the Time layout, so leaving it shows the universe as it is now.
  setLayout: (layout) => set((s) => ({ layout, timeCut: layout === 'time' ? s.timeCut : null })),
  setTimeCut: (timeCut) => set({ timeCut }),
  // Anything that replaces or closes the viewer asks first when a note has unsaved changes.
  openViewer: (viewerItemId) => {
    if (viewerItemId !== get().viewerItemId && !discardOk(get())) return;
    set({ viewerItemId, selectedItemId: viewerItemId, dashboardProjectId: null, viewerDirty: false });
  },
  closeViewer: () => {
    if (!discardOk(get())) return;
    set({ viewerItemId: null, dashboardProjectId: null, viewerDirty: false });
  },
  setViewerDirty: (viewerDirty) => set({ viewerDirty }),
  openDashboard: (dashboardProjectId) => {
    if (!discardOk(get())) return;
    set({
      dashboardProjectId,
      selectedProjectId: dashboardProjectId,
      viewerItemId: null,
      viewerDirty: false,
    });
  },
  flyHome: () => set((s) => ({ homeTick: s.homeTick + 1, selectedItemId: null, selectedProjectId: null })),
  initQuality: (webgl) => {
    const s = get();
    if (s.quality !== null) return;
    set({ quality: s.qualitySetting === 'auto' ? detectQuality(webglRenderer(), webgl) : s.qualitySetting });
  },
  setQualitySetting: (qualitySetting) => {
    saveQualitySetting(qualitySetting);
    set({
      qualitySetting,
      quality: qualitySetting === 'auto' ? detectQuality(webglRenderer(), true) : qualitySetting,
    });
  },
  degradeQuality: () => {
    const s = get();
    if (s.qualitySetting !== 'auto' || s.quality === null || s.quality === 'lite') return;
    const next = stepDown(s.quality);
    set({ quality: next });
    s.addNotice(
      'info',
      `The universe dropped to ${QUALITY_LABEL[next]} to keep frames smooth (System → Display)`,
    );
  },
  setTextScale: (textScale) => {
    saveNumber('universe.textScale', textScale);
    document.documentElement.style.fontSize = `${textScale * 100}%`;
    set({ textScale });
  },
  setHighContrast: (highContrast) => {
    saveNumber('universe.highContrast', highContrast ? 1 : 0);
    document.documentElement.dataset.contrast = highContrast ? 'high' : 'normal';
    set({ highContrast });
  },
  zoomOut: () => {
    const s = get();
    if (s.viewerItemId || s.dashboardProjectId) s.closeViewer();
    else if (s.selectedItemId) set({ selectedItemId: null });
    else if (s.selectedProjectId) set({ selectedProjectId: null });
    else return false;
    return true;
  },
}));

function loadNumber(key: string, fallback: number): number {
  try {
    const value = Number(localStorage.getItem(key));
    return localStorage.getItem(key) !== null && Number.isFinite(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

function saveNumber(key: string, value: number): void {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    // Storage unavailable: the choice lasts for this session.
  }
}

/** `agent.step` names what a tool works on; a finished task's probe returns to the Core. */
export function applyProbeTarget(targets: Record<string, ProbeTarget>, event: CoreEvent) {
  const p = event.payload as { agent_id?: string; target?: ProbeTarget };
  if (!p.agent_id) return targets;
  if (event.type === 'agent.step' && p.target && (p.target.kind === 'item' || p.target.kind === 'project')) {
    return { ...targets, [p.agent_id]: { kind: p.target.kind, id: String(p.target.id) } };
  }
  if ((event.type === 'agent.completed' || event.type === 'agent.failed') && p.agent_id in targets) {
    const next = { ...targets };
    delete next[p.agent_id];
    return next;
  }
  return targets;
}

/** Navigator's ui.show: an agent asked the HUD to show you something. */
function navigate({ target, value }: { target?: string; value?: string }) {
  if (!value) return;
  const s = useUniverse.getState();
  if (target === 'project') {
    s.selectProject(value);
    if (s.view === 'universe') s.setView('grid');
  } else if (target === 'item') s.selectItem(value);
  else if (target === 'search') {
    s.setQuery(value);
    s.focusResults();
  }
}
