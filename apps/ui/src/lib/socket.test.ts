import type { CoreEvent } from '@universe/shared-types';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CoreSocket, reconnectDelay, type ConnectionState } from './socket';

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }
  close() {
    this.onclose?.();
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

const event = (seq: number | null, type = 'chat.message'): CoreEvent => ({
  id: `e${seq}`,
  seq,
  ts: '2026-10-12T10:00:00Z',
  type,
  source: 'core',
  actor: 'system',
  subject_type: null,
  subject_id: null,
  correlation_id: null,
  causation_id: null,
  payload: {},
  v: 1,
});

describe('CoreSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
  });
  afterEach(() => vi.useRealTimers());

  function setup() {
    let lastSeq = 5;
    const states: ConnectionState[] = [];
    const received: CoreEvent[] = [];
    let tickets = 0;
    const socket = new CoreSocket({
      wsUrl: 'ws://127.0.0.1:1/ws',
      getTicket: async () => `t${++tickets}`,
      lastSeq: () => lastSeq,
      onState: (s) => states.push(s),
      onEvent: (e) => {
        received.push(e);
        if (e.seq) lastSeq = e.seq;
      },
      WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
      random: () => 0.5,
    });
    return { socket, states, received, setLast: (n: number) => (lastSeq = n) };
  }

  it('connects with a fresh ticket and resumes after the last applied seq', async () => {
    const { socket, states } = setup();
    socket.start();
    await vi.runOnlyPendingTimersAsync();
    expect(FakeSocket.instances[0]!.url).toBe('ws://127.0.0.1:1/ws?ticket=t1&since_seq=5');
    FakeSocket.instances[0]!.onopen?.();
    expect(states).toEqual(['connecting', 'online']);
    socket.stop();
  });

  it('drops events it has already applied', async () => {
    const { socket, received } = setup();
    socket.start();
    await vi.runOnlyPendingTimersAsync();
    const ws = FakeSocket.instances[0]!;
    ws.emit({ kind: 'event', event: event(4) });
    ws.emit({ kind: 'event', event: event(6) });
    ws.emit({ kind: 'event', event: event(null, 'chat.token') });
    ws.emit({ kind: 'ack', op: 'ping' });
    expect(received.map((e) => e.seq)).toEqual([6, null]);
    socket.stop();
  });

  it('reconnects with backoff and a new ticket after the connection drops', async () => {
    const { socket, states } = setup();
    socket.start();
    await vi.runOnlyPendingTimersAsync();
    FakeSocket.instances[0]!.onopen?.();
    FakeSocket.instances[0]!.close();
    expect(states.at(-1)).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(reconnectDelay(1, () => 0.5));
    expect(FakeSocket.instances).toHaveLength(2);
    expect(FakeSocket.instances[1]!.url).toContain('ticket=t2');
    socket.stop();
  });

  it('caps the reconnect delay at about five seconds', () => {
    expect(reconnectDelay(1, () => 0.5)).toBe(250);
    expect(reconnectDelay(3, () => 0.5)).toBe(1000);
    expect(reconnectDelay(50, () => 1)).toBeLessThanOrEqual(6250);
  });
});
