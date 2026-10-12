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
}
