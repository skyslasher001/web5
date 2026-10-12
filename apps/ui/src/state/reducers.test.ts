import type { CoreEvent } from '@universe/shared-types';
import { describe, expect, it } from 'vitest';
import { applyAgentEvent, applyChatEvent, describeEvent, type ChatState } from './reducers';

let seq = 0;
function ev(type: string, payload: Record<string, unknown>, actor = 'agent:core'): CoreEvent {
  seq += 1;
  return {
    id: `e${seq}`,
    seq,
    ts: '2026-10-12T10:00:00.000Z',
    type,
    source: 'core',
    actor,
    subject_type: 'conversation',
    subject_id: 'c1',
    correlation_id: null,
    causation_id: null,
    payload,
    v: 1,
  };
}

const stored = (id: string, role: 'user' | 'assistant', content: string, status = 'complete') => ({
  id,
  conversation_id: 'c1',
  role,
  agent_id: role === 'user' ? null : 'core',
  content,
  model: role === 'user' ? null : 'm',
  status,
  first_token_ms: null,
  total_ms: null,
  created_at: '2026-10-12T10:00:00.000Z',
});

function run(state: ChatState, events: CoreEvent[]): ChatState {
  return events.reduce(applyChatEvent, state);
}

describe('chat reducer', () => {
  const base: ChatState = { conversationId: 'c1', messages: [] };

  it('streams tokens into a placeholder and settles on the stored message', () => {
    const state = run(base, [
      ev('chat.message', stored('u1', 'user', 'hi'), 'user'),
      ev('chat.started', { conversation_id: 'c1', message_id: 'a1', model: 'm' }),
      ev('chat.token', { conversation_id: 'c1', message_id: 'a1', delta: 'Hel' }),
      ev('chat.token', { conversation_id: 'c1', message_id: 'a1', delta: 'lo' }),
    ]);
    expect(state.messages.map((m) => [m.role, m.content, m.status])).toEqual([
      ['user', 'hi', 'complete'],
      ['assistant', 'Hello', 'streaming'],
    ]);
    const done = run(state, [
      ev('chat.message', stored('a1', 'assistant', 'Hello')),
      ev('chat.completed', { conversation_id: 'c1', message_id: 'a1', first_token_ms: 12, total_ms: 40 }),
    ]);
    expect(done.messages[1]).toMatchObject({
      content: 'Hello',
      status: 'complete',
      firstTokenMs: 12,
      totalMs: 40,
    });
  });

  it('ignores other conversations and events before a conversation is open', () => {
    const other = ev('chat.token', { conversation_id: 'c2', message_id: 'x', delta: 'nope' });
    expect(run(base, [other]).messages).toEqual([]);
    expect(run({ conversationId: null, messages: [] }, [other]).messages).toEqual([]);
  });

  it('keeps the error and hint of a failed reply', () => {
    const state = run(base, [
      ev('chat.failed', {
        conversation_id: 'c1',
        message_id: 'a1',
        code: 'no_model',
        error: 'No model',
        hint: 'Run: ollama pull x',
      }),
    ]);
    expect(state.messages[0]).toMatchObject({
      status: 'failed',
      error: { code: 'no_model', hint: 'Run: ollama pull x' },
    });
  });

  it('marks an in-flight reply as failed when Core restarts', () => {
    const state = run(base, [
      ev('chat.started', { conversation_id: 'c1', message_id: 'a1', model: 'm' }),
      ev('service.started', { service: 'core', pid: 2 }, 'system'),
    ]);
    expect(state.messages[0]).toMatchObject({ status: 'failed', error: { code: 'restart' } });
  });

  it('does not append tokens to a finished message', () => {
    const state = run(base, [
      ev('chat.message', stored('a1', 'assistant', 'Done')),
      ev('chat.token', { conversation_id: 'c1', message_id: 'a1', delta: ' late' }),
    ]);
    expect(state.messages[0]!.content).toBe('Done');
  });
});

describe('agent activity', () => {
  it('follows the task lifecycle', () => {
    let agents = {};
    agents = applyAgentEvent(agents, ev('agent.started', { agent_id: 'core' }));
    expect(agents).toEqual({ core: 'thinking' });
    agents = applyAgentEvent(agents, ev('chat.token', { delta: 'x' }));
    expect(agents).toEqual({ core: 'replying' });
    agents = applyAgentEvent(agents, ev('agent.failed', { agent_id: 'core' }));
    expect(agents).toEqual({ core: 'error' });
    agents = applyAgentEvent(agents, ev('agent.completed', { agent_id: 'core' }));
    expect(agents).toEqual({ core: 'idle' });
  });
});

describe('activity lines', () => {
  it('describes restarts and hides noise', () => {
    expect(
      describeEvent(ev('service.restarted', { service: 'core', reason: 'crash', last_exit: '-9' }, 'system')),
    ).toEqual({
      tone: 'warn',
      text: 'Core restarted after a crash (exit -9)',
    });
    expect(describeEvent(ev('chat.token', { delta: 'x' }))).toBeNull();
  });
});
