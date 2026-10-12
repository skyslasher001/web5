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
    case 'agent.completed':
      return p.cancelled
        ? { tone: 'info', text: 'Core reply stopped' }
        : {
            tone: 'info',
            text: `Core replied${p.first_token_ms != null ? ` · first token ${p.first_token_ms} ms` : ''}`,
          };
    case 'chat.failed':
      return { tone: 'bad', text: `Reply failed: ${str(p.error)}` };
    case 'error.raised':
      return { tone: 'bad', text: `Error in ${str(p.service)}: ${str(p.kind)}` };
    case 'project.created':
      return { tone: 'info', text: `Galaxy created: ${str(p.name)}` };
    case 'model.assignment_changed':
      return { tone: 'info', text: `Chat model set to ${str(p.model)}` };
    default:
      return null;
  }
}
