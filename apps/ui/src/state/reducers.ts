// Pure event → state reducers (unit-tested). The store applies them to every Core event.
import type { CoreEvent, Message } from '@universe/shared-types';

export type MessageStatus = 'streaming' | 'complete' | 'cancelled' | 'failed';

export interface ChatError {
  code: string;
  error: string;
  hint: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  status: MessageStatus;
  model: string | null;
  firstTokenMs: number | null;
  totalMs: number | null;
  error: ChatError | null;
  /** The agent task behind this reply (its trace), when Core answered through the engine. */
  taskId: string | null;
  createdAt: string;
}

export interface ChatState {
  conversationId: string | null;
  messages: ChatMessage[];
}

export type AgentActivity = 'idle' | 'thinking' | 'replying' | 'error';

export interface ActivityItem {
  id: string;
  ts: string;
  tone: 'info' | 'good' | 'warn' | 'bad';
  text: string;
  /** Lines of the same group arriving close together merge into one ("Added 37 items"). */
  group?: string;
  count?: number;
}

const GROUP_WINDOW_MS = 10_000;
const GROUP_TEXT: Record<string, (count: number) => string> = {
  'item.created': (n) => `Added ${n} items`,
};

/** Put a new line at the top, merging it into the top line when both belong to the same burst. */
export function pushActivity(list: ActivityItem[], next: ActivityItem, limit: number): ActivityItem[] {
  const top = list[0];
  const text = next.group ? GROUP_TEXT[next.group] : undefined;
  if (
    text &&
    top !== undefined &&
    top.group === next.group &&
    Math.abs(Date.parse(next.ts) - Date.parse(top.ts)) <= GROUP_WINDOW_MS
  ) {
    const count = (top.count ?? 1) + 1;
    return [{ ...top, ts: next.ts, count, text: text(count) }, ...list.slice(1)];
  }
  return [next, ...list].slice(0, limit);
}

type Payload = Record<string, unknown>;
const str = (v: unknown): string => (typeof v === 'string' ? v : '');
const num = (v: unknown): number | null => (typeof v === 'number' ? v : null);

export function fromStored(m: Message): ChatMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    status: m.status,
    model: m.model ?? null,
    firstTokenMs: m.first_token_ms ?? null,
    totalMs: m.total_ms ?? null,
    error: null,
    taskId: m.task_id ?? null,
    createdAt: m.created_at,
  };
}

function upsert(messages: ChatMessage[], id: string, update: (m: ChatMessage | undefined) => ChatMessage) {
  const index = messages.findIndex((m) => m.id === id);
  if (index === -1) return [...messages, update(undefined)];
  const next = messages.slice();
  next[index] = update(messages[index]);
  return next;
}

function placeholder(id: string, ts: string): ChatMessage {
  return {
    id,
    role: 'assistant',
    content: '',
    status: 'streaming',
    model: null,
    firstTokenMs: null,
    totalMs: null,
    error: null,
    taskId: null,
    createdAt: ts,
  };
}

export function applyChatEvent(state: ChatState, event: CoreEvent): ChatState {
  const p = event.payload as Payload;
  if (event.type === 'service.started' && p.service === 'core') {
    // Core restarted: any reply that was streaming will never finish.
    const messages = state.messages.map((m) =>
      m.status === 'streaming'
        ? {
            ...m,
            status: 'failed' as const,
            error: { code: 'restart', error: 'Core restarted while replying.', hint: 'Send it again.' },
          }
        : m,
    );
    return { ...state, messages };
  }
  if (!event.type.startsWith('chat.') || !state.conversationId) return state;
  if (str(p.conversation_id) !== state.conversationId) return state;
  const id = str(p.message_id) || str(p.id);
  switch (event.type) {
    case 'chat.message': {
      const stored = fromStored(p as unknown as Message);
      return { ...state, messages: upsert(state.messages, stored.id, () => stored) };
    }
    case 'chat.started':
      return {
        ...state,
        messages: upsert(state.messages, id, (m) => ({
          ...(m ?? placeholder(id, event.ts)),
          model: str(p.model),
        })),
      };
    case 'chat.token':
      return {
        ...state,
        messages: upsert(state.messages, id, (m) => {
          const base = m ?? placeholder(id, event.ts);
          return base.status === 'streaming' ? { ...base, content: base.content + str(p.delta) } : base;
        }),
      };
    case 'chat.completed':
    case 'chat.cancelled':
      return {
        ...state,
        messages: upsert(state.messages, id, (m) => ({
          ...(m ?? placeholder(id, event.ts)),
          status:
            m && m.status !== 'streaming'
              ? m.status
              : event.type === 'chat.completed'
                ? 'complete'
                : 'cancelled',
          firstTokenMs: num(p.first_token_ms),
          totalMs: num(p.total_ms),
        })),
      };
    case 'chat.failed':
      return {
        ...state,
        messages: upsert(state.messages, id, (m) => ({
          ...(m ?? placeholder(id, event.ts)),
          status: 'failed',
          error: { code: str(p.code), error: str(p.error), hint: str(p.hint) },
          taskId: str(p.task_id) || (m?.taskId ?? null),
        })),
      };
    default:
      return state;
  }
}

export function applyAgentEvent(agents: Record<string, AgentActivity>, event: CoreEvent) {
  const p = event.payload as Payload;
  const agent = str(p.agent_id) || (event.actor.startsWith('agent:') ? event.actor.slice(6) : '');
  if (!agent) return agents;
  switch (event.type) {
    case 'agent.started':
      return { ...agents, [agent]: 'thinking' as const };
    case 'chat.token':
      return agents[agent] === 'replying' ? agents : { ...agents, [agent]: 'replying' as const };
    case 'agent.completed':
      return { ...agents, [agent]: 'idle' as const };
    case 'agent.failed':
      return { ...agents, [agent]: 'error' as const };
    default:
      return agents;
  }
}

const TOOL_STEP: Record<string, string> = {
  'vault.search': 'Searching your vault…',
  'vault.read': 'Reading an item…',
  'project.list': 'Looking at your galaxies…',
  'project.add_items': 'Linking items to a galaxy…',
  'note.create': 'Writing a note…',
  'memory.search': 'Checking memory…',
  'memory.save': 'Saving a memory…',
  'ui.show': 'Showing it to you…',
  'agent.delegate': 'Asking a specialist…',
  critic: 'Critic is checking the work…',
};

/** What an agent is doing right now, in words ("Searching your vault…"), from its latest step. */
export function stepLabel(kind: string, tool: string | null, decision: string | null): string {
  if (decision === 'ask') return 'Waiting for your OK…';
  if (kind === 'llm_call') return 'Thinking…';
  if (!tool) return 'Working…';
  if (tool.startsWith('mcp.')) return `Using ${tool.split('.').slice(1).join(' · ')}…`;
  return TOOL_STEP[tool] ?? `Using ${tool}…`;
}

export function applyStepEvent(steps: Record<string, string>, event: CoreEvent): Record<string, string> {
  const p = event.payload as Payload;
  const agent = str(p.agent_id);
  if (!agent) return steps;
  if (event.type === 'agent.step') {
    // A tool's result is followed by another model call: keep showing the tool until then.
    if (str(p.kind) === 'tool_result') return steps;
    const decision = typeof p.decision === 'string' ? p.decision : null;
    const tool = typeof p.tool === 'string' ? p.tool : null;
    return { ...steps, [agent]: stepLabel(str(p.kind), tool, decision) };
  }
  if (event.type === 'agent.completed' || event.type === 'agent.failed') {
    if (!(agent in steps)) return steps;
    const next = { ...steps };
    delete next[agent];
    return next;
  }
  return steps;
}

const TIER_ROLE: Record<string, string> = {
  'local-fast': 'Chat model',
  'local-large': 'Large model',
  embed_text: 'Search model',
  vision: 'Image model',
};

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** One human-readable line for the activity ribbon, or null for events that would only be noise. */
export function describeEvent(event: CoreEvent): Omit<ActivityItem, 'id' | 'ts'> | null {
  const p = event.payload as Payload;
  switch (event.type) {
    case 'service.started':
      return {
        tone: 'good',
        text: `${p.safe_mode ? 'Core started in safe mode' : 'Core started'} (pid ${p.pid})`,
      };
    case 'service.restarted':
      return {
        tone: 'warn',
        text: `Core restarted after a ${str(p.reason) === 'crash' ? 'crash' : str(p.reason)}${p.last_exit ? ` (exit ${p.last_exit})` : ''}`,
      };
    case 'safe_mode.entered':
      return { tone: 'bad', text: 'Safe mode: agents disabled' };
    case 'agent.completed': {
      const name = capitalize(str(p.agent_id) || 'core');
      // A specialist's sub-task shows up as its parent's progress, not as its own line.
      if (p.parent_id) return null;
      if (p.cancelled) return { tone: 'info', text: `${name} stopped` };
      if (p.steps != null) return { tone: 'info', text: `${name} finished · ${num(p.steps)} steps` };
      return {
        tone: 'info',
        text: `${name} replied${p.first_token_ms != null ? ` · first token ${p.first_token_ms} ms` : ''}`,
      };
    }
    case 'agent.failed':
      if (p.parent_id) return null;
      return { tone: 'bad', text: `${capitalize(str(p.agent_id) || 'core')} failed: ${str(p.error)}` };
    case 'approval.requested':
      return {
        tone: 'warn',
        text: `${capitalize(str(p.agent_id))} asks: ${str(p.summary)}`,
      };
    case 'approval.decided':
      return { tone: 'info', text: `${p.approved ? 'Approved' : 'Declined'}: ${str(p.tool)}` };
    case 'approval.expired':
      return { tone: 'warn', text: 'An approval expired without an answer' };
    case 'memory.proposed':
      return { tone: 'info', text: 'An agent proposed a memory: review it in Agents → Memory' };
    case 'killswitch.engaged':
      return { tone: 'bad', text: 'Kill switch engaged: all agents stopped' };
    case 'killswitch.released':
      return { tone: 'good', text: 'Kill switch released' };
    case 'budget.warning':
      return {
        tone: 'warn',
        text: `Budget: ${Math.round((num(p.level) ?? 0) * 100)} % of this month's cap used`,
      };
    case 'budget.cap_reached':
      return { tone: 'bad', text: 'Budget cap reached: paid models are stopped until next month' };
    case 'chat.failed':
      return { tone: 'bad', text: `Reply failed: ${str(p.error)}` };
    case 'error.raised':
      return { tone: 'bad', text: `Error in ${str(p.service)}: ${str(p.kind)}` };
    case 'project.created':
      return { tone: 'info', text: `Galaxy created: ${str(p.name)}` };
    case 'model.assignment_changed': {
      const role = TIER_ROLE[str(p.tier)] ?? 'Chat model';
      return { tone: 'info', text: p.model ? `${role} set to ${str(p.model)}` : `${role} cleared` };
    }
    case 'item.created':
      return { tone: 'good', text: `Added ${str(p.title) || 'an item'}`, group: 'item.created' };
    case 'item.trashed':
      // Trashing from the app already shows a line; this is the vault noticing a file was deleted.
      return p.reason ? { tone: 'warn', text: `Moved to the trash: ${str(p.reason)}` } : null;
    case 'item.restored':
      return { tone: 'info', text: 'Restored an item from the trash' };
    case 'item.deleted':
      return { tone: 'info', text: 'Deleted an item permanently' };
    case 'job.dead':
      return { tone: 'bad', text: `Processing gave up (${str(p.kind)}): ${str(p.error)}` };
    case 'backup.completed':
      return {
        tone: 'good',
        text: `Backup completed${p.snapshot_id ? ` · snapshot ${str(p.snapshot_id).slice(0, 8)}` : ''}`,
      };
    case 'backup.failed':
      return { tone: 'bad', text: `${capitalize(str(p.operation) || 'backup')} failed: ${str(p.error)}` };
    case 'backup.restored':
      return { tone: 'good', text: `Backup restored to ${str(p.target)}` };
    case 'backup.restore_tested':
      return { tone: 'good', text: `Restore test passed · ${num(p.items) ?? 0} items readable` };
    case 'governor.paused':
      return { tone: 'warn', text: `Background work paused${p.reason ? `: ${str(p.reason)}` : ''}` };
    case 'governor.resumed':
      return { tone: 'info', text: 'Background work resumed' };
    default:
      return null;
  }
}
