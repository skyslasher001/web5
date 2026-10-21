// PROTECTED CORE (protected-core.txt): launches the supervisor and is the only holder of its
// control token. Forge may never modify this file; apply/rollback will route through here (Phase 5).
import { spawn, type ChildProcess } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { createInterface } from 'node:readline';
import type { DesktopState, LogName, ServiceName, SupervisorStatus } from '@universe/shared-types';
import type { Logger } from '../logger';

export type SupervisorLine =
  { event: 'ready'; control_port: number; core_url: string } | { event: 'status'; status: SupervisorStatus };

/** One release as the supervisor's /releases control endpoints report it (ForgeControl consumes this). */
export interface SupervisorRelease {
  tag: string;
  commit: string;
  proposal_id: string | null;
  title: string;
  created_at: number;
  status: 'watching' | 'good' | 'rolled_back';
  current: boolean;
}

export function parseSupervisorLine(line: string): SupervisorLine | null {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    return null;
  }
  if (typeof value !== 'object' || value === null) return null;
  const msg = value as Record<string, unknown>;
  if (msg.event === 'ready' && typeof msg.control_port === 'number') return msg as SupervisorLine;
  if (msg.event === 'status' && typeof msg.status === 'object' && msg.status !== null)
    return msg as SupervisorLine;
  return null;
}

export function restartDelayMs(restarts: number): number {
  return Math.min(30_000, 1000 * 2 ** Math.max(0, Math.min(restarts - 1, 5)));
}

export interface SupervisorOptions {
  python: string;
  script: string;
  cwd: string;
  env: NodeJS.ProcessEnv;
  token: string;
  log: Logger;
}

export class SupervisorProcess extends EventEmitter {
  state: DesktopState = { supervisor: null, process: 'starting', lastError: null };
  private child: ChildProcess | null = null;
  private controlPort: number | null = null;
  private stopping = false;
  private restarts = 0;
  private restartTimer: NodeJS.Timeout | null = null;

  constructor(private readonly opts: SupervisorOptions) {
    super();
  }

  start(): void {
    this.stopping = false;
    const { python, script, cwd, env, log } = this.opts;
    log.info('supervisor_spawn', { python, script });
    const child = spawn(python, ['-I', '-S', script], {
      cwd,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    this.child = child;
    createInterface({ input: child.stdout! }).on('line', (line) => this.onLine(line));
    createInterface({ input: child.stderr! }).on('line', (line) => log.warn('supervisor_stderr', { line }));
    child.on('error', (err) => {
      log.error('supervisor_spawn_failed', { error: String(err) });
      this.setState({ process: 'failed', lastError: `Could not start the supervisor: ${err.message}` });
    });
    child.on('exit', (code, signal) => {
      this.child = null;
      this.controlPort = null;
      if (this.stopping) {
        this.setState({ process: 'stopped' });
        return;
      }
      this.restarts += 1;
      const delay = restartDelayMs(this.restarts);
      log.error('supervisor_exited', { code, signal, restart_in_ms: delay });
      this.setState({
        process: 'restarting',
        lastError: `Supervisor exited (code ${code ?? signal}); restarting`,
      });
      this.restartTimer = setTimeout(() => this.start(), delay);
    });
  }

  private onLine(line: string): void {
    const msg = parseSupervisorLine(line);
    if (!msg) {
      this.opts.log.warn('supervisor_stdout_unparsed', { line: line.slice(0, 500) });
      return;
    }
    if (msg.event === 'ready') {
      this.controlPort = msg.control_port;
      this.setState({ process: 'running', lastError: null });
      this.emit('ready');
    } else {
      this.setState({ supervisor: msg.status });
    }
  }

  private setState(patch: Partial<DesktopState>): void {
    this.state = { ...this.state, ...patch };
    this.emit('state', this.state);
  }

  private async request<T>(
    method: 'GET' | 'POST',
    path: string,
    payload?: unknown,
    timeoutMs = 5000,
  ): Promise<T> {
    if (this.controlPort === null) throw new Error('The supervisor is not running');
    const response = await fetch(`http://127.0.0.1:${this.controlPort}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.opts.token}`,
        ...(payload === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      signal: AbortSignal.timeout(timeoutMs),
    });
    const body = (await response.json()) as T;
    if (!response.ok && response.status !== 409)
      throw new Error(`supervisor ${path}: HTTP ${response.status}`);
    return body;
  }

  async restartService(name: ServiceName): Promise<boolean> {
    return (await this.request<{ ok: boolean }>('POST', `/services/${name}/restart`)).ok;
  }

  async killService(name: 'core'): Promise<boolean> {
    return (await this.request<{ ok: boolean }>('POST', `/services/${name}/kill`)).ok;
  }

  async setKillSwitch(engaged: boolean): Promise<{ engaged: boolean; core_acked: boolean }> {
    return this.request('POST', '/killswitch', { engaged });
  }

  // ---------- releases (Phase 5): only ForgeControl calls these, after your native-dialog confirmation ----------

  async applyRelease(
    body: Record<string, string>,
  ): Promise<{ ok: boolean; error?: string; release?: SupervisorRelease }> {
    return this.request('POST', '/releases/apply', body, 60_000);
  }

  async rollbackRelease(tag: string): Promise<{ ok: boolean; error?: string; release?: SupervisorRelease }> {
    return this.request('POST', '/releases/rollback', { release: tag }, 60_000);
  }

  async listReleases(): Promise<{ available: boolean; releases: SupervisorRelease[] }> {
    return this.request('GET', '/releases');
  }

  async exitSafeMode(): Promise<boolean> {
    return (await this.request<{ ok: boolean }>('POST', '/safe-mode/exit')).ok;
  }

  async logs(name: Exclude<LogName, 'desktop'>, lines = 200): Promise<string> {
    return (await this.request<{ text: string }>('GET', `/logs/${name}?tail=${lines}`)).text;
  }

  async stop(): Promise<void> {
    this.stopping = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    const child = this.child;
    if (!child) return;
    const exited = new Promise<void>((resolve) => child.once('exit', () => resolve()));
    try {
      await this.request('POST', '/shutdown');
    } catch {
      child.stdin?.end(); // EOF on stdin also makes the supervisor shut down
    }
    const timeout = new Promise<'timeout'>((resolve) => setTimeout(() => resolve('timeout'), 8000));
    if ((await Promise.race([exited, timeout])) === 'timeout') child.kill();
  }
}
