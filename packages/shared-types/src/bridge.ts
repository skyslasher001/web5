// The typed API Electron's preload exposes as `window.universe` (the only renderer → OS path).

export interface BridgeConfig {
  coreUrl: string;
  wsUrl: string;
  token: string;
  version: string;
  platform: string;
  dev: boolean;
  /** Width in px reserved on the right of the top bar for native window controls. */
  windowControlsWidth: number;
}

export interface SupervisorServiceStatus {
  state: string;
  pid: number | null;
  restarts: number;
  healthy_since: number | null;
  last_exit_code: number | null;
  last_error: string | null;
  health_url: string | null;
}

export interface SupervisorStatus {
  supervisor: { version: string; pid: number; started_at: number };
  core_url: string;
  safe_mode: {
    active: boolean;
    reason: string | null;
    running_from: string | null;
    lkg_commit: string | null;
  };
  services: Record<string, SupervisorServiceStatus>;
}

export type SupervisorProcessState = 'starting' | 'running' | 'restarting' | 'stopped' | 'failed';

export interface DesktopState {
  supervisor: SupervisorStatus | null;
  process: SupervisorProcessState;
  lastError: string | null;
}

export type ServiceName = 'core' | 'ollama';
export type LogName = ServiceName | 'supervisor' | 'desktop';

export interface ErrorReportInput {
  kind: string;
  message: string;
  stack?: string;
}

export interface HotkeyStatus {
  accelerator: string;
  registered: boolean;
  error: string | null;
}

export interface ClipboardCaptureResult {
  kind: 'text' | 'image' | 'empty';
  ok: boolean;
  message: string;
}

export interface UniverseBridge {
  getConfig(): Promise<BridgeConfig>;
  getDesktopState(): Promise<DesktopState>;
  onDesktopState(callback: (state: DesktopState) => void): () => void;
  restartService(name: ServiceName): Promise<boolean>;
  /** Hard-kills a service the way a crash would, to see the watchdog recover it. */
  killService(name: 'core'): Promise<boolean>;
  exitSafeMode(): Promise<boolean>;
  getLogs(name: LogName, lines?: number): Promise<string>;
  openLogsFolder(): Promise<void>;
  reportError(report: ErrorReportInput): void;
  reload(): void;

  // ---------- vault (Phase 2) ----------
  /** Absolute paths of files dropped on the window (Electron's webUtils; File.path is gone). */
  pathsForFiles(files: File[]): string[];
  /** Opens a vault file with its default app. Refuses anything outside the vault. Resolves to an error or ''. */
  openPath(absPath: string): Promise<string>;
  /** Shows a vault file in Explorer. Refuses anything outside the vault. */
  revealPath(absPath: string): Promise<boolean>;
  pickFolder(title: string): Promise<string | null>;
  /** Saves whatever is on the clipboard (text, link or image) to the vault inbox. */
  captureClipboard(): Promise<ClipboardCaptureResult>;

  // ---------- command bar (global hotkey window) ----------
  getHotkey(): Promise<HotkeyStatus>;
  setHotkey(accelerator: string): Promise<HotkeyStatus>;
  showCommandBar(mode?: 'search' | 'capture'): void;
  hideCommandBar(): void;
  /** Fired in the command-bar window each time it is shown. */
  onCommandBarShow(callback: (mode: 'search' | 'capture') => void): () => void;
  /** Brings the main window forward and shows an item, a galaxy or search results (from the command bar). */
  focus(target: FocusTarget): void;
  /** Fired in the main window when the command bar asks to show something. */
  onFocus(callback: (target: FocusTarget) => void): () => void;

  // ---------- kill switch (Phase 3; owned by protected Electron main code) ----------
  getKillSwitch(): Promise<KillSwitchState>;
  /** Engaging is instant. Releasing shows a native dialog you must confirm. */
  setKillSwitch(engaged: boolean): Promise<KillSwitchState>;
  onKillSwitch(callback: (state: KillSwitchState) => void): () => void;

  // ---------- Forge releases (Phase 5; owned by protected Electron main code and the supervisor) ----------
  /** Approve a Forge proposal: a native dialog shows it, and only then does the supervisor apply it. */
  forgeApprove(proposalId: string): Promise<ForgeDecision>;
  /** Roll back to a release (a native dialog asks first). */
  forgeRollback(release: string): Promise<ForgeDecision>;
  getReleases(): Promise<ReleasesState>;
}

export interface ForgeDecision {
  ok: boolean;
  message: string;
  release?: string;
}

export interface ReleaseInfo {
  tag: string;
  commit: string;
  created_at: string;
  proposal_id: string | null;
  title: string;
  status: 'watching' | 'good' | 'rolled_back';
  current: boolean;
}

export interface ReleasesState {
  /** False until the Phase 5 protected-core patch is applied. */
  available: boolean;
  reason?: string;
  releases: ReleaseInfo[];
}

export interface KillSwitchState {
  /** False until the Phase 3 protected-core patch is applied. */
  available: boolean;
  engaged: boolean;
}

/** What the command bar can ask the main window to show. */
export type FocusTarget =
  { kind: 'item'; id: string } | { kind: 'project'; id: string } | { kind: 'search'; query: string };
