// Typed REST client for Core. Types are generated from the backend's OpenAPI schema.
import type {
  AgentInfo,
  AgentTask,
  Approval,
  AuditEntry,
  AuditVerification,
  BudgetStatus,
  EngineStatus,
  KillSwitchStatus,
  MCPServerInfo,
  MCPServerRequest,
  Memory,
  PermissionRule,
  TaskDetail,
  ApiKeyCreated,
  ApiKeyInfo,
  BackupConfigRequest,
  BackupRecord,
  BackupStatus,
  CaptureRequest,
  CaptureResult,
  ChatSendResponse,
  Conversation,
  DeleteResult,
  EventPage,
  HardwareInfo,
  IngestResult,
  Item,
  ItemPage,
  ItemPatch,
  ItemText,
  ItemType,
  Message,
  ModelsInfo,
  OpenResult,
  Project,
  QueueStats,
  RecallResult,
  Recommendation,
  SearchResponse,
  Snapshot,
  VaultInfo,
  Vitals,
  WatchedFolder,
  WatchedFolderCreate,
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

export type AssignableTier = 'local-fast' | 'local-large' | 'embed_text' | 'vision';
export type ItemSort = 'added' | 'captured' | 'opened' | 'title';

export interface ItemQuery {
  types?: ItemType[];
  project?: string | null;
  tag?: string | null;
  pinned?: boolean;
  trashed?: boolean;
  sort?: ItemSort;
  cursor?: string | null;
  limit?: number;
}

export interface SearchQuery {
  q: string;
  mode?: 'keyword' | 'hybrid';
  types?: ItemType[];
  project?: string | null;
  limit?: number;
}

/** Query string from a flat object: arrays repeat the key, empty values are dropped. */
export function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)));
    else search.append(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export class CoreApi {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
    private readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  private async send(method: string, path: string, body?: BodyInit, json = false): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/v1${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.token}`,
          ...(json ? { 'Content-Type': 'application/json' } : {}),
        },
        body,
      });
    } catch {
      throw new ApiError(0, 'Core is not reachable');
    }
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const problem = (await response.json()) as { detail?: unknown };
        if (typeof problem.detail === 'string') detail = problem.detail;
        else if (Array.isArray(problem.detail) && problem.detail.length)
          detail = String((problem.detail[0] as { msg?: string }).msg ?? detail); // validation errors
      } catch {
        // keep the status text
      }
      throw new ApiError(response.status, detail);
    }
    return response;
  }

  private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await this.send(
      method,
      path,
      body === undefined ? undefined : JSON.stringify(body),
      body !== undefined,
    );
    return (await response.json()) as T;
  }

  wsTicket = () => this.call<WsTicket>('POST', '/session/ws-ticket');
  vitals = () => this.call<Vitals>('GET', '/system/vitals');
  hardware = () => this.call<HardwareInfo>('GET', '/system/hardware');
  recommendation = () => this.call<Recommendation>('GET', '/models/recommendation');
  models = () => this.call<ModelsInfo>('GET', '/models');
  assignModel = (tier: AssignableTier, model: string) =>
    this.call<ModelsInfo>('PUT', '/models/assignments', { tier, model });
  clearModel = (tier: AssignableTier) => this.call<ModelsInfo>('DELETE', `/models/assignments/${tier}`);
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

  // ---------- vault ----------
  items = (q: ItemQuery) =>
    this.call<ItemPage>(
      'GET',
      `/items${queryString({
        type: q.types,
        project: q.project,
        tag: q.tag,
        pinned: q.pinned,
        trashed: q.trashed,
        sort: q.sort,
        cursor: q.cursor,
        limit: q.limit,
      })}`,
    );
  item = (id: string) => this.call<Item>('GET', `/items/${id}`);
  patchItem = (id: string, patch: ItemPatch) => this.call<Item>('PATCH', `/items/${id}`, patch);
  deleteItem = (id: string, permanent = false) =>
    this.call<DeleteResult>('DELETE', `/items/${id}${permanent ? '?permanent=true' : ''}`);
  restoreItem = (id: string) => this.call<Item>('POST', `/items/${id}/restore`);
  openItem = (id: string) => this.call<OpenResult>('POST', `/items/${id}/open`);
  reprocessItem = (id: string) => this.call<Item>('POST', `/items/${id}/reprocess`);
  itemText = (id: string, limit = 4000) => this.call<ItemText>('GET', `/items/${id}/text?limit=${limit}`);
  /** The thumbnail as a Blob (images need the auth header, so <img src> can't fetch them directly). */
  thumbnail = async (id: string): Promise<Blob> => (await this.send('GET', `/items/${id}/thumbnail`)).blob();
  search = (q: SearchQuery) =>
    this.call<SearchResponse>(
      'GET',
      `/search${queryString({ q: q.q, mode: q.mode, type: q.types, project: q.project, limit: q.limit })}`,
    );
  recall = (q: string) => this.call<RecallResult>('POST', '/recall', { q });
  ingestPaths = (paths: string[], projectId?: string | null) =>
    this.call<IngestResult>('POST', '/ingest/paths', { paths, project_id: projectId ?? null });
  capture = (body: CaptureRequest) => this.call<CaptureResult>('POST', '/capture', body);
  vaultInfo = () => this.call<VaultInfo>('GET', '/system/vault');
  jobStats = () => this.call<QueueStats>('GET', '/jobs/stats');
  pauseQueue = () => this.call<QueueStats>('POST', '/queue/pause');
  resumeQueue = () => this.call<QueueStats>('POST', '/queue/resume');

  watchedFolders = () => this.call<WatchedFolder[]>('GET', '/watched-folders');
  addWatchedFolder = (body: WatchedFolderCreate) =>
    this.call<WatchedFolder>('POST', '/watched-folders', body);
  setWatchedFolderEnabled = (id: string, enabled: boolean) =>
    this.call<WatchedFolder>('PATCH', `/watched-folders/${id}`, { enabled });
  removeWatchedFolder = (id: string) => this.call<WatchedFolder>('DELETE', `/watched-folders/${id}`);
  scanWatchedFolder = (id: string) => this.call<WatchedFolder>('POST', `/watched-folders/${id}/scan`);

  backupStatus = () => this.call<BackupStatus>('GET', '/backups/status');
  configureBackups = (body: BackupConfigRequest) => this.call<BackupStatus>('PUT', '/backups/config', body);
  runBackup = () => this.call<{ started: boolean }>('POST', '/backups/run');
  verifyBackup = () => this.call<{ started: boolean }>('POST', '/backups/verify');
  backupHistory = () => this.call<BackupRecord[]>('GET', '/backups');
  snapshots = () => this.call<Snapshot[]>('GET', '/backups/snapshots');
  restoreBackup = (snapshotId: string, target: string) =>
    this.call<{ started: boolean }>('POST', '/backups/restore', { snapshot_id: snapshotId, target });

  apiKeys = () => this.call<ApiKeyInfo[]>('GET', '/api-keys');
  createApiKey = (name: string, scopes: Array<'capture' | 'search'>) =>
    this.call<ApiKeyCreated>('POST', '/api-keys', { name, scopes });
  revokeApiKey = (id: string) => this.call<ApiKeyInfo>('DELETE', `/api-keys/${id}`);

  // ---------- agent engine ----------
  engine = () => this.call<EngineStatus>('GET', '/engine');
  runAgent = (agentId: string, instruction: string) =>
    this.call<{ task_id: string }>('POST', `/agents/${agentId}/run`, { instruction });
  tasks = (q: { agent?: string; status?: string; limit?: number } = {}) =>
    this.call<AgentTask[]>('GET', `/tasks${queryString(q)}`);
  task = (id: string) => this.call<TaskDetail>('GET', `/tasks/${id}`);
  cancelTask = (id: string) => this.call<AgentTask>('POST', `/tasks/${id}/cancel`);
  /** Approvals waiting for you. */
  approvals = () => this.call<Approval[]>('GET', '/approvals');
  decideApproval = (id: string, approve: boolean, remember = false) =>
    this.call<Approval>('POST', `/approvals/${id}/decision`, { approve, remember });

  memories = (status?: 'active' | 'proposed') =>
    this.call<Memory[]>('GET', `/memories${queryString({ status })}`);
  createMemory = (content: string, scope = 'self') =>
    this.call<Memory>('POST', '/memories', { content, scope });
  decideMemory = (id: string, approve: boolean) =>
    this.call<Memory>('POST', `/memories/${id}/decision`, { approve });
  editMemory = (id: string, content: string) => this.call<Memory>('PATCH', `/memories/${id}`, { content });
  deleteMemory = (id: string) => this.send('DELETE', `/memories/${id}`).then(() => undefined);

  permissionRules = () => this.call<PermissionRule[]>('GET', '/permissions/rules');
  addPermissionRule = (
    rule: Pick<PermissionRule, 'agent_id' | 'tool' | 'decision' | 'applies_when_tainted'>,
  ) => this.call<PermissionRule>('POST', '/permissions/rules', rule);
  removePermissionRule = (id: string) =>
    this.send('DELETE', `/permissions/rules/${id}`).then(() => undefined);
  budget = () => this.call<BudgetStatus>('GET', '/budget');
  setBudgetCap = (monthlyCapUsd: number) =>
    this.call<BudgetStatus>('PUT', '/budget/caps', { monthly_cap_usd: monthlyCapUsd });
  killSwitch = () => this.call<KillSwitchStatus>('GET', '/killswitch');
  /** Core can only engage the kill switch; releasing it takes the desktop's native dialog. */
  engageKillSwitch = () => this.call<KillSwitchStatus>('POST', '/killswitch', { engaged: true });
  audit = (limit = 100, action?: string) =>
    this.call<AuditEntry[]>('GET', `/audit${queryString({ limit, action })}`);
  verifyAudit = () => this.call<AuditVerification>('GET', '/audit/verify');

  mcpServers = () => this.call<MCPServerInfo[]>('GET', '/mcp/servers');
  addMcpServer = (body: MCPServerRequest) => this.call<MCPServerInfo>('POST', '/mcp/servers', body);
  setMcpServerEnabled = (id: string, enabled: boolean) =>
    this.call<MCPServerInfo>('POST', `/mcp/servers/${id}/enabled`, { enabled });
  restartMcpServer = (id: string) => this.call<MCPServerInfo>('POST', `/mcp/servers/${id}/restart`);
  removeMcpServer = (id: string) => this.send('DELETE', `/mcp/servers/${id}`).then(() => undefined);
}
