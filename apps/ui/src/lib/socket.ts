// WebSocket to Core with single-use tickets, automatic reconnect and gap-free resume (since_seq).
import type { CoreEvent } from '@universe/shared-types';

export type ConnectionState = 'connecting' | 'online' | 'reconnecting';

export interface SocketOptions {
  wsUrl: string;
  getTicket: () => Promise<string>;
  onEvent: (event: CoreEvent, replay: boolean) => void;
  onState: (state: ConnectionState, attempt: number) => void;
  /** Highest persisted seq already applied; the server replays anything newer on (re)connect. */
  lastSeq: () => number;
  WebSocketImpl?: typeof WebSocket;
  random?: () => number;
}

export function reconnectDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(5000, 250 * 2 ** Math.max(0, attempt - 1));
  return Math.round(base * (0.75 + random() * 0.5));
}

export class CoreSocket {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(private readonly opts: SocketOptions) {}

  start(): void {
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    this.opts.onState(this.attempt === 0 ? 'connecting' : 'reconnecting', this.attempt);
    let ticket: string;
    try {
      ticket = await this.opts.getTicket();
    } catch {
      this.scheduleReconnect();
      return;
    }
    if (this.stopped) return;
    const Impl = this.opts.WebSocketImpl ?? WebSocket;
    const url = `${this.opts.wsUrl}?ticket=${encodeURIComponent(ticket)}&since_seq=${this.opts.lastSeq()}`;
    const ws = new Impl(url);
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.opts.onState('online', 0);
    };
    ws.onmessage = (message: MessageEvent) => {
      let data: { kind?: string; event?: CoreEvent; replay?: boolean };
      try {
        data = JSON.parse(String(message.data));
      } catch {
        return;
      }
      if (data.kind !== 'event' || !data.event) return;
      const seq = data.event.seq;
      if (seq !== null && seq !== undefined && seq <= this.opts.lastSeq()) return; // already applied
      this.opts.onEvent(data.event, Boolean(data.replay));
    };
    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.attempt += 1;
    this.opts.onState('reconnecting', this.attempt);
    this.timer = setTimeout(() => void this.connect(), reconnectDelay(this.attempt, this.opts.random));
  }
}
