// Electron main: window, app:// protocol, supervisor, IPC, error capture, safe mode.
import { BrowserWindow, app, ipcMain, net, protocol, session, shell } from 'electron';
import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import type {
  BridgeConfig,
  DesktopState,
  ErrorReportInput,
  LogName,
  ServiceName,
} from '@universe/shared-types';
import { CH } from './channels';
import { createLogger } from './logger';
import { resolvePaths } from './paths';
import { buildCsp, contentType, resolveAppFile } from './protocol';
import { SupervisorProcess } from './protected/supervisor';

const env = process.env;
const paths = resolvePaths(__dirname, env, process.platform);
const corePort = Number(env.UNIVERSE_CORE_PORT ?? 47821);
const coreUrl = `http://127.0.0.1:${corePort}`;
const devUiUrl = env.UNIVERSE_UI_URL; // set by `pnpm dev` (Vite); otherwise the built UI via app://
const sessionToken = randomBytes(32).toString('base64url');
const controlToken = randomBytes(32).toString('base64url');
const log = createLogger(join(paths.logDir, 'desktop.jsonl'), [sessionToken, controlToken]);
const allowedOrigins = ['app://universe', ...(devUiUrl ? [new URL(devUiUrl).origin] : [])];

if (env.UNIVERSE_USER_DATA_DIR) app.setPath('userData', env.UNIVERSE_USER_DATA_DIR);

// Local-first: stop Chromium's own background traffic (component updates, field trials, etc.).
app.commandLine.appendSwitch('disable-background-networking');
app.commandLine.appendSwitch('disable-component-update');
// Chromium's spellchecker downloads Hunspell dictionaries from Google as soon as a session exists.
// Turn it off at session creation (before the download starts) and point any download at nowhere.
app.on('session-created', (created) => {
  created.setSpellCheckerEnabled(false);
  created.setSpellCheckerLanguages([]);
  created.setSpellCheckerDictionaryDownloadURL('http://127.0.0.1:9/');
});

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
]);

// ---------- error capture (forwarded to Core's error store once it is up) ----------

const pendingErrors: Array<Record<string, unknown>> = [];

async function flushErrors(): Promise<void> {
  while (pendingErrors.length) {
    const report = pendingErrors[0];
    try {
      const response = await net.fetch(`${coreUrl}/api/v1/errors`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(report),
      });
      if (!response.ok) return;
      pendingErrors.shift();
    } catch {
      return; // Core not reachable yet; retried on the next healthy status
    }
  }
}

function captureError(service: 'desktop' | 'renderer', input: ErrorReportInput): void {
  log.error('error_captured', { service, kind: input.kind, message: input.message });
  if (pendingErrors.length < 50) {
    pendingErrors.push({
      service,
      kind: String(input.kind).slice(0, 200) || 'Error',
      message: String(input.message ?? '').slice(0, 2000),
      stack: String(input.stack ?? '').slice(0, 20000),
    });
  }
  void flushErrors();
}

process.on('uncaughtException', (err) =>
  captureError('desktop', { kind: err.name, message: err.message, stack: err.stack }),
);
process.on('unhandledRejection', (reason) => {
  const err = reason instanceof Error ? reason : new Error(String(reason));
  captureError('desktop', { kind: err.name, message: err.message, stack: err.stack });
});

// ---------- supervisor ----------

const supervisor = new SupervisorProcess({
  python: paths.basePython,
  script: paths.supervisorScript,
  cwd: paths.repoRoot,
  token: controlToken,
  log,
  env: {
    ...env,
    UNIVERSE_SUPERVISOR_TOKEN: controlToken,
    UNIVERSE_SESSION_TOKEN: sessionToken,
    UNIVERSE_DATA_DIR: paths.dataDir,
    UNIVERSE_VAULT_DIR: paths.vaultDir,
    UNIVERSE_REPO_ROOT: paths.repoRoot,
    UNIVERSE_SERVICE_PYTHON: paths.venvPython,
    UNIVERSE_CORE_PORT: String(corePort),
    UNIVERSE_ALLOWED_ORIGINS: allowedOrigins.join(','),
    UNIVERSE_SUPERVISOR_WATCH_STDIN: '1',
  },
});

let win: BrowserWindow | null = null;
let showingSafeMode = false;
const rendererCrashes: number[] = [];

function send(state: DesktopState): void {
  if (win && !win.isDestroyed()) win.webContents.send(CH.desktopState, state);
}

supervisor.on('state', (state: DesktopState) => {
  send(state);
  const core = state.supervisor?.services.core;
  if (core?.state === 'healthy') void flushErrors();
  if (state.supervisor?.safe_mode.active && core?.state === 'failed') showSafeMode('core-failed');
});

// ---------- window ----------

function loadMainUi(): void {
  if (!win) return;
  showingSafeMode = false;
  void (devUiUrl ? win.loadURL(devUiUrl) : win.loadURL('app://universe/index.html'));
}

function showSafeMode(reason: string): void {
  if (!win || showingSafeMode) return;
  showingSafeMode = true;
  log.error('safe_mode_page', { reason });
  void win.loadFile(join(paths.safeModeDir, 'index.html'), { query: { reason } });
}

function createWindow(): void {
  const overlay = process.platform !== 'darwin';
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    title: 'UNIVERSE',
    backgroundColor: '#05070D',
    titleBarStyle: 'hidden',
    ...(overlay ? { titleBarOverlay: { color: '#05070D', symbolColor: '#A9B4D0', height: 36 } } : {}),
    webPreferences: {
      preload: paths.preload,
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
    },
  });
  win.once('ready-to-show', () => win?.show());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => {
    const allowed =
      url.startsWith('app://universe/') ||
      url.startsWith('file://') ||
      (devUiUrl && url.startsWith(devUiUrl));
    if (!allowed) event.preventDefault();
  });
  win.webContents.on('did-fail-load', (_e, code, description, url) => {
    log.error('ui_failed_to_load', { code, description, url });
    if (!showingSafeMode && code !== -3) showSafeMode('ui-failed-to-load');
  });
  win.webContents.on('render-process-gone', (_e, details) => {
    log.error('renderer_gone', { reason: details.reason, exitCode: details.exitCode });
    const now = Date.now();
    rendererCrashes.push(now);
    while (rendererCrashes.length && now - rendererCrashes[0]! > 60_000) rendererCrashes.shift();
    if (rendererCrashes.length >= 2) showSafeMode('renderer-crashed');
    else loadMainUi();
  });
  win.on('closed', () => {
    win = null;
  });
  loadMainUi();
}

// ---------- IPC ----------

const SERVICES: ServiceName[] = ['core', 'ollama'];
const LOGS: LogName[] = ['core', 'ollama', 'supervisor', 'desktop'];

function registerIpc(): void {
  ipcMain.handle(CH.getConfig, (): BridgeConfig => ({
    coreUrl,
    wsUrl: `ws://127.0.0.1:${corePort}/ws`,
    token: sessionToken,
    version: app.getVersion(),
    platform: process.platform,
    dev: Boolean(devUiUrl),
    windowControlsWidth: process.platform === 'darwin' ? 0 : 140,
  }));
  ipcMain.handle(CH.getDesktopState, () => supervisor.state);
  ipcMain.handle(CH.restartService, (_e, name: unknown) =>
    SERVICES.includes(name as ServiceName) ? supervisor.restartService(name as ServiceName) : false,
  );
  ipcMain.handle(CH.killService, (_e, name: unknown) =>
    name === 'core' ? supervisor.killService('core') : false,
  );
  ipcMain.handle(CH.exitSafeMode, () => supervisor.exitSafeMode());
  ipcMain.handle(CH.getLogs, async (_e, name: unknown, lines: unknown) => {
    if (!LOGS.includes(name as LogName)) return '';
    const count = Math.max(1, Math.min(Number(lines) || 200, 2000));
    if (name === 'desktop') {
      const file = join(paths.logDir, 'desktop.jsonl');
      return existsSync(file) ? readFileSync(file, 'utf8').split('\n').slice(-count).join('\n') : '';
    }
    return supervisor.logs(name as Exclude<LogName, 'desktop'>, count);
  });
  ipcMain.handle(CH.openLogsFolder, async () => {
    await shell.openPath(paths.logDir);
  });
  ipcMain.on(CH.reportError, (_e, report: ErrorReportInput) =>
    captureError('renderer', report ?? { kind: 'Error', message: '' }),
  );
  ipcMain.on(CH.reload, () => loadMainUi());
}

// ---------- lifecycle ----------

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(() => {
    const csp = buildCsp(corePort);
    protocol.handle('app', async (request) => {
      const file = resolveAppFile(paths.uiDist, request.url);
      if (!file || !existsSync(file)) return new Response('Not found', { status: 404 });
      const upstream = await net.fetch(pathToFileURL(file).toString());
      return new Response(upstream.body, {
        headers: { 'content-type': contentType(file), 'content-security-policy': csp },
      });
    });
    // Mic, camera, screen, notifications…: denied until the consent system lands (Phases 7–8).
    session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) =>
      callback(permission === 'clipboard-sanitized-write'),
    );
    session.defaultSession.setPermissionCheckHandler(
      (_wc, permission) => permission === 'clipboard-sanitized-write',
    );
    registerIpc();
    log.info('app_ready', {
      repo: paths.repoRoot,
      vault: paths.vaultDir,
      dev: Boolean(devUiUrl),
      core_port: corePort,
    });
    supervisor.start();
    createWindow();
  });

  let quitting = false;
  app.on('before-quit', (event) => {
    if (quitting) return;
    event.preventDefault();
    quitting = true;
    void supervisor.stop().finally(() => app.quit());
  });
  app.on('window-all-closed', () => app.quit());
}
