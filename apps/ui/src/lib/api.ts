// Typed REST client for Core. Types are generated from the backend's OpenAPI schema.
import type {
  ForgeIssue,
  ForgeProposal,
  ForgeStatus,
  ResearchResponse,
  SentRequest,
  MemoSaved,
  VoiceModelInfo,
  VoiceSettingsUpdate,
  VoiceStatus,
  VoicesResponse,
  Watchlist,
  WatchlistHit,
  AgentCreate,
  AgentInfo,
  AgentProfile,
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
  ErrorRecord,
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
  ItemLinks,
  ItemPatch,
  ItemSummary,
  ItemText,
  ItemType,
  Message,
  NoteContent,
  ModelsInfo,
  OpenResult,
  Project,
  ProjectGoal,
  QueueStats,
  RecallResult,
  Recommendation,
  SearchResponse,
  SemanticLayout,
  Snapshot,
  UniverseItems,
  UniverseLinks,
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
  patchProject = (id: string, patch: { description?: string; status?: string; goals?: ProjectGoal[] }) =>
    this.call<Project>('PATCH', `/projects/${id}`, patch);
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
  errors = () => this.call<ErrorRecord[]>('GET', '/errors?limit=50');
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

  // ---------- the universe view ----------
  universeItems = (q: { cursor?: string | null; since?: string | null; limit?: number } = {}) =>
    this.call<UniverseItems>('GET', `/universe/items${queryString(q)}`);
  universeLinks = () => this.call<UniverseLinks>('GET', '/universe/links');
  semanticLayout = () => this.call<SemanticLayout>('GET', '/layout/semantic');
  itemLinks = (id: string) => this.call<ItemLinks>('GET', `/items/${id}/links`);
  addLink = (fromId: string, toId: string) =>
    this.call<{ id: string }>('POST', '/links', { from_id: fromId, to_id: toId });
  removeLink = (id: string) => this.send('DELETE', `/links/${id}`).then(() => undefined);
  noteContent = (id: string) => this.call<NoteContent>('GET', `/items/${id}/content`);
  saveNote = (id: string, body: string, baseVersion: number) =>
    this.call<NoteContent>('PUT', `/items/${id}/content`, { body, base_version: baseVersion });
  similarItems = (id: string, limit = 12) =>
    this.call<ItemSummary[]>('GET', `/items/${id}/similar?limit=${limit}`);
  /** The item's file as a Blob (media and PDFs need the auth header, so a plain src can't load them). */
  itemFile = async (id: string): Promise<Blob> => (await this.send('GET', `/items/${id}/file`)).blob();

  // ---------- agent engine ----------
  engine = () => this.call<EngineStatus>('GET', '/engine');
  agentRoster = () => this.call<AgentProfile[]>('GET', '/agents/roster');
  forgeStatus = () => this.call<ForgeStatus>('GET', '/forge/status');
  forgeIssues = () => this.call<ForgeIssue[]>('GET', '/forge/issues');
  forgeReport = (text: string) => this.call<ForgeIssue>('POST', '/forge/reports', { text });
  forgeFix = (issueId: string) => this.call<{ task_id: string }>('POST', `/forge/issues/${issueId}/fix`);
  forgeIgnore = (issueId: string) => this.call<ForgeIssue>('POST', `/forge/issues/${issueId}/ignore`);
  forgeProposals = () => this.call<ForgeProposal[]>('GET', '/forge/proposals');
  forgeReject = (id: string) => this.call<ForgeProposal>('POST', `/forge/proposals/${id}/reject`);

  // ---------- research (Phase 6) ----------
  research = (q: string, mode: 'quick' | 'deep') =>
    this.call<ResearchResponse>('POST', '/research', { q, mode });
  sentRequests = () => this.call<SentRequest[]>('GET', '/research/requests?limit=50');
  watchlists = () => this.call<Watchlist[]>('GET', '/watchlists');
  createWatchlist = (body: { kind: 'topic' | 'page'; target: string; label?: string; interval_s?: number }) =>
    this.call<Watchlist>('POST', '/watchlists', body);
  setWatchlistEnabled = (id: string, enabled: boolean) =>
    this.call<Watchlist>('PATCH', `/watchlists/${id}`, { enabled });
  deleteWatchlist = (id: string) => this.send('DELETE', `/watchlists/${id}`).then(() => undefined);
  watchlistHits = (id: string) => this.call<WatchlistHit[]>('GET', `/watchlists/${id}/hits`);
  checkWatchlist = (id: string) => this.call<Watchlist>('POST', `/watchlists/${id}/check`);
  // ---------- voice (Phase 7) ----------
  voiceStatus = () => this.call<VoiceStatus>('GET', '/voice/status');
  voiceStart = () => this.call<VoiceStatus>('POST', '/voice/start');
  voiceStop = () => this.call<VoiceStatus>('POST', '/voice/stop');
  voiceSettings = (body: VoiceSettingsUpdate) => this.call<VoiceStatus>('PUT', '/voice/settings', body);
  voices = () => this.call<VoicesResponse>('GET', '/voices');
  installVoiceModel = (id: string) => this.call<VoiceModelInfo>('POST', `/voice/models/${id}/install`);
  /** A recorded memo (WAV). Stored as a voice_memo; the pipeline transcribes it. */
  saveMemo = async (wav: Blob, title?: string): Promise<MemoSaved> => {
    const response = await this.fetchImpl(`${this.baseUrl}/api/v1/voice/memo${queryString({ title })}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'audio/wav' },
      body: wav,
    }).catch(() => {
      throw new ApiError(0, 'Core is not reachable');
    });
    if (!response.ok) throw new ApiError(response.status, `Saving the memo failed (HTTP ${response.status})`);
    return (await response.json()) as MemoSaved;
  };

  addAgent = (body: AgentCreate) => this.call<AgentProfile>('POST', '/agents', body);
  updateAgent = (id: string, body: { enabled?: boolean; synopsis?: string }) =>
    this.call<AgentProfile>('PATCH', `/agents/${id}`, body);
  removeAgent = (id: string) => this.send('DELETE', `/agents/${id}`).then(() => undefined);
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
