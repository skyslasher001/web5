export type * from './bridge';
export type { components, paths } from './api';
export { EVENT_TYPES } from './events';
export type { EventType } from './events';

import type { components } from './api';

type Schemas = components['schemas'];
export type CoreEvent = Schemas['Event'];
export type Project = Schemas['Project'];
export type Message = Schemas['Message'];
export type Conversation = Schemas['Conversation'];
export type Vitals = Schemas['Vitals'];
export type HardwareInfo = Schemas['HardwareInfo'];
export type Recommendation = Schemas['Recommendation'];
export type ModelsInfo = Schemas['ModelsInfo'];
export type AgentInfo = Schemas['AgentInfo'];
export type AgentProfile = Schemas['AgentProfile'];
export type ForgeStatus = Schemas['ForgeStatus'];
export type ForgeIssue = Schemas['ForgeIssue'];
export type ForgeProposal = Schemas['ForgeProposal'];
export type AgentCreate = Schemas['AgentCreate'];
export type ChatSendResponse = Schemas['ChatSendResponse'];
export type WsTicket = Schemas['WsTicket'];
export type EventPage = Schemas['EventPage'];

// Vault (Phase 2)
export type Item = Schemas['Item'];
export type ItemSummary = Schemas['ItemSummary'];
export type ItemType = Schemas['ItemSummary']['type'];
export type ItemStage = Schemas['ItemStage'];
export type ItemPage = Schemas['ItemPage'];
export type ItemText = Schemas['ItemText'];
export type ItemPatch = Schemas['ItemPatch'];
export type OpenResult = Schemas['OpenResult'];
export type DeleteResult = Schemas['DeleteResult'];
export type SearchResponse = Schemas['SearchResponse'];
export type SearchHit = Schemas['SearchHit'];
export type ParsedQuery = Schemas['ParsedQuery'];
export type FilterChip = Schemas['FilterChip'];
export type RecallResult = Schemas['RecallResult'];
export type IngestResult = Schemas['IngestResult'];
export type CaptureRequest = Schemas['CaptureRequest'];
export type CaptureResult = Schemas['CaptureResult'];
export type QueueStats = Schemas['QueueStats'];
export type JobInfo = Schemas['JobInfo'];
export type VaultInfo = Schemas['VaultInfo'];
export type WatchedFolder = Schemas['WatchedFolder'];
export type WatchedFolderCreate = Schemas['WatchedFolderCreate'];
export type BackupStatus = Schemas['BackupStatus'];
export type BackupRecord = Schemas['BackupRecord'];
export type ErrorRecord = Schemas['ErrorRecord'];
export type LoadedModel = Schemas['LoadedModel'];
export type BackupConfigRequest = Schemas['BackupConfigRequest'];
export type Snapshot = Schemas['Snapshot'];
export type ApiKeyInfo = Schemas['ApiKeyInfo'];
export type ApiKeyCreated = Schemas['ApiKeyCreated'];

// Phase 3: the agent engine
export type AgentTask = Schemas['AgentTask'];
export type TaskStep = Schemas['TaskStep'];
export type TaskDetail = Schemas['TaskDetail'];
export type Approval = Schemas['Approval'];
export type Memory = Schemas['Memory'];
export type EngineStatus = Schemas['EngineStatus'];
export type KillSwitchStatus = Schemas['KillSwitchStatus'];
export type MCPServerInfo = Schemas['MCPServerInfo'];
export type MCPServerRequest = Schemas['MCPServerRequest'];
export type AuditEntry = Schemas['AuditEntry'];
export type AuditVerification = Schemas['AuditVerification'];

// These come from the protected policy engine (not in the OpenAPI schema: its models live in protected code).
export interface PermissionRule {
  id: string;
  agent_id: string;
  tool: string;
  decision: 'allow' | 'ask' | 'deny';
  applies_when_tainted: boolean;
  created_at: string;
  expires_at: string | null;
}

export interface UsageRow {
  key: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  calls: number;
}

export interface BudgetStatus {
  month: string;
  monthly_cap_usd: number;
  spent_usd: number;
  tokens_in: number;
  tokens_out: number;
  calls: number;
  by_agent: UsageRow[];
  by_model: UsageRow[];
}

// Phase 6: research
export type Watchlist = Schemas['Watchlist'];
export type WatchlistHit = Schemas['WatchlistHit'];
export type SentRequest = Schemas['SentRequest'];
export type ResearchResponse = Schemas['ResearchResponse'];

// Phase 7: voice
export type VoiceStatus = Schemas['VoiceStatus'];
export type VoiceModelInfo = Schemas['VoiceModelInfo'];
export type VoiceSettings = Schemas['VoiceSettings'];
export type VoicesResponse = Schemas['VoicesResponse'];
export type AgentVoice = Schemas['AgentVoice'];
export type MemoSaved = Schemas['MemoSaved'];
export type VoiceSettingsUpdate = Schemas['VoiceSettingsUpdate'];

// Phase 4: the universe view
export type UniverseItems = Schemas['UniverseItems'];
export type UniverseLinks = Schemas['UniverseLinks'];
export type SemanticLayout = Schemas['SemanticLayout'];
export type ItemLinks = Schemas['ItemLinks'];
export type LinkInfo = Schemas['LinkInfo'];
export type NoteContent = Schemas['NoteContent'];
export type ProjectGoal = Schemas['ProjectGoal'];
