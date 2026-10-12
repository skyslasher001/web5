// Typed REST client for Core. Types are generated from the backend's OpenAPI schema.
import type {
  AgentInfo,
  ChatSendResponse,
  Conversation,
  EventPage,
  HardwareInfo,
  Message,
  ModelsInfo,
  Project,
  Recommendation,
  Vitals,
  WsTicket,
} from '@universe/shared-types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export class CoreApi {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
    private readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/v1${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.token}`,
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, 'Core is not reachable');
    }
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const problem = (await response.json()) as { detail?: unknown };
        if (typeof problem.detail === 'string') detail = problem.detail;
      } catch {
        // keep the status text
      }
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
  }

  wsTicket = () => this.call<WsTicket>('POST', '/session/ws-ticket');
  vitals = () => this.call<Vitals>('GET', '/system/vitals');
  hardware = () => this.call<HardwareInfo>('GET', '/system/hardware');
  recommendation = () => this.call<Recommendation>('GET', '/models/recommendation');
  models = () => this.call<ModelsInfo>('GET', '/models');
  assignModel = (tier: 'local-fast' | 'local-large', model: string) =>
    this.call<ModelsInfo>('PUT', '/models/assignments', { tier, model });
  agents = () => this.call<AgentInfo[]>('GET', '/agents');
  projects = () => this.call<Project[]>('GET', '/projects');
  conversations = () => this.call<Conversation[]>('GET', '/conversations?limit=20');
  messages = (conversationId: string) =>
    this.call<Message[]>('GET', `/conversations/${conversationId}/messages`);
  sendChat = (text: string, conversationId: string) =>
    this.call<ChatSendResponse>('POST', '/chat', { text, conversation_id: conversationId });
  cancelChat = (conversationId: string) =>
    this.call<{ cancelled: boolean }>('POST', `/conversations/${conversationId}/cancel`);
  recentEvents = (tail: number) => this.call<EventPage>('GET', `/events?tail=${tail}`);
}
