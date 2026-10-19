// Electron main: windows, app:// protocol, supervisor, IPC, error capture, safe mode, command bar, tray.
import {
  BrowserWindow,
  app,
  clipboard,
  dialog,
  globalShortcut,
  ipcMain,
  net,
  protocol,
  session,
  shell,
  type Tray,
} from 'electron';
import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import type {
  BridgeConfig,
  DesktopState,
  ErrorReportInput,
  HotkeyStatus,
  LogName,
  ServiceName,
} from '@universe/shared-types';
import { CH } from './channels';
import { captureClipboard, clipboardSource } from './clipboardCapture';
import { CommandBar, type CommandBarMode } from './commandBar';
import { isValidAccelerator, loadSettings, saveSettings } from './desktopSettings';
import { createErrorQueue } from './errorQueue';
import { parseFocusTarget } from './focusTarget';
import { createLogger } from './logger';
import { isAllowedNavigation } from './navigation';
import { resolvePaths } from './paths';
import { buildCsp, contentType, isServableFile, resolveAppFile } from './protocol';
import { KILL_SWITCH_HOTKEY, KillSwitchControl, readKillSwitchFile } from './protected/killswitch';
import { SupervisorProcess } from './protected/supervisor';
import { createTray } from './tray';
import { insideFolder } from './vaultAccess';

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

const errorQueue = createErrorQueue(
  async (report) => {
    const response = await net.fetch(`${coreUrl}/api/v1/errors`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(report),
    });
    return response.status;
  },
  (status) => log.warn('error_report_rejected', { status }),
);

function captureError(service: 'desktop' | 'renderer', input: ErrorReportInput): void {
  log.error('error_captured', { service, kind: input.kind, message: input.message });
  errorQueue.push({
    service,
    kind: String(input.kind).slice(0, 200) || 'Error',
    message: String(input.message ?? '').slice(0, 2000),
    stack: String(input.stack ?? '').slice(0, 20000),
  });
  void errorQueue.flush();
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
  if (core?.state === 'healthy') void errorQueue.flush();
  if (state.supervisor?.safe_mode.active && core?.state === 'failed') showSafeMode('core-failed');
});

// ---------- window ----------

function uiUrl(hash = ''): string {
  return devUiUrl ? `${devUiUrl}${hash}` : `app://universe/index.html${hash}`;
}

function loadMainUi(): void {
  if (!win) return;
  showingSafeMode = false;
  void win.loadURL(uiUrl());
}

function showMainWindow(): void {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
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
    if (!isAllowedNavigation(url, { devUiUrl, safeModeDir: paths.safeModeDir })) {
      log.warn('navigation_blocked', { url: url.slice(0, 200) });
      event.preventDefault();
    }
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
    app.quit(); // the hidden command-bar window must not keep the app alive
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

  // ---------- vault: main opens and reveals files, but only inside the vault ----------
  ipcMain.handle(CH.openPath, async (_e, absPath: unknown) => {
    if (typeof absPath !== 'string' || !insideFolder(paths.vaultDir, absPath)) {
      log.warn('open_path_refused', { path: String(absPath).slice(0, 200) });
      return 'Only files inside the vault can be opened';
    }
    return shell.openPath(absPath);
  });
  ipcMain.handle(CH.revealPath, (_e, absPath: unknown) => {
    if (typeof absPath !== 'string' || !insideFolder(paths.vaultDir, absPath)) return false;
    shell.showItemInFolder(absPath);
    return true;
  });
  ipcMain.handle(CH.pickFolder, async (event, title: unknown) => {
    const owner = BrowserWindow.fromWebContents(event.sender) ?? undefined;
    const options = {
      title: typeof title === 'string' ? title.slice(0, 120) : 'Choose a folder',
      properties: ['openDirectory', 'createDirectory'] as Array<'openDirectory' | 'createDirectory'>,
    };
    const result = owner ? await dialog.showOpenDialog(owner, options) : await dialog.showOpenDialog(options);
    return result.canceled ? null : (result.filePaths[0] ?? null);
  });
  ipcMain.handle(CH.captureClipboard, saveClipboard);

  // ---------- kill switch (protected control) ----------
  // ---------- Forge releases ----------
  // Approval and apply live in protected code (Phase 5 protected-core patch); until it's applied, there is none.
  const NO_RELEASES = 'Applying Forge changes needs the Phase 5 protected-core patch (docs/proposals).';
  ipcMain.handle(CH.forgeApprove, () => ({ ok: false, message: NO_RELEASES }));
  ipcMain.handle(CH.forgeRollback, () => ({ ok: false, message: NO_RELEASES }));
  ipcMain.handle(CH.getReleases, () => ({ available: false, reason: NO_RELEASES, releases: [] }));

  // ---------- consent ----------
  // The mic belongs to protected code (Phase 7 protected-core patch); until it's applied, it can't be turned on.
  const NO_CONSENT = {
    available: false,
    mic: false,
    reason: 'The microphone needs the Phase 7 protected-core patch (docs/proposals/phase-7-consent.md).',
  };
  ipcMain.handle(CH.getConsent, () => NO_CONSENT);
  ipcMain.handle(CH.setMicConsent, () => NO_CONSENT);

  ipcMain.handle(CH.getKillSwitch, () => ({ available: true, engaged: killSwitch.engaged }));
  ipcMain.handle(CH.setKillSwitch, async (_e, engaged: unknown) => {
    if (typeof engaged !== 'boolean') return { available: true, engaged: killSwitch.engaged };
    const result = await killSwitch.set(engaged, 'hud');
    return { available: true, engaged: result.engaged };
  });

  // ---------- command bar ----------
  ipcMain.handle(CH.getHotkey, (): HotkeyStatus => commandBar?.status ?? noHotkey());
  ipcMain.handle(CH.setHotkey, (_e, accelerator: unknown): HotkeyStatus => {
    if (typeof accelerator !== 'string' || !isValidAccelerator(accelerator)) {
      return {
        ...(commandBar?.status ?? noHotkey()),
        error: 'Use a modifier plus a key, e.g. Ctrl+Shift+Space',
      };
    }
    const status = commandBar?.register(accelerator) ?? noHotkey();
    if (status.registered) saveSettings(settingsFile(), { commandBarHotkey: accelerator });
    return status;
  });
  ipcMain.on(CH.showCommandBar, (_e, mode: unknown) =>
    commandBar?.show(mode === 'capture' ? 'capture' : 'search'),
  );
  ipcMain.on(CH.hideCommandBar, () => commandBar?.hide());
  ipcMain.on(CH.focus, (_e, value: unknown) => {
    const target = parseFocusTarget(value);
    if (!target) return;
    commandBar?.hide();
    showMainWindow();
    win?.webContents.send(CH.focusEvent, target);
  });
}

const killSwitch = new KillSwitchControl({
  initial: readKillSwitchFile(join(paths.dataDir, 'killswitch.json')),
  setOnSupervisor: (engaged) => supervisor.setKillSwitch(engaged),
  stopCapture: () => {}, // no capture exists yet; mic, screen and camera arrive in Phases 7–8
  confirmRelease: async () => {
    const options = {
      type: 'warning' as const,
      buttons: ['Keep it on', 'Release'],
      defaultId: 0,
      cancelId: 0,
      title: 'Release the kill switch?',
      message: 'Release the kill switch?',
      detail:
        'Agents and network jobs can run again. Mic, screen and camera stay off until you turn them on.',
    };
    const choice = win ? await dialog.showMessageBox(win, options) : await dialog.showMessageBox(options);
    return choice.response === 1;
  },
  onChange: (engaged) => {
    for (const w of BrowserWindow.getAllWindows()) {
      w.webContents.send(CH.killSwitchEvent, { available: true, engaged });
    }
  },
  log: (event, fields) => log.warn(event, fields),
});

let commandBar: CommandBar | null = null;
let tray: Tray | null = null;

function saveClipboard() {
  return captureClipboard(clipboardSource(clipboard), coreUrl, sessionToken, (input, init) =>
    net.fetch(input as string, init),
  );
}

function noHotkey(): HotkeyStatus {
  return { accelerator: '', registered: false, error: 'The command bar is not ready' };
}

function settingsFile(): string {
  return join(app.getPath('userData'), 'desktop-settings.json');
}

function startCommandBarAndTray(): void {
  commandBar = new CommandBar({
    preload: paths.preload,
    url: uiUrl('#command-bar'),
    log,
    isAllowedNavigation: (url) => isAllowedNavigation(url, { devUiUrl, safeModeDir: paths.safeModeDir }),
  });
  commandBar.create();
  commandBar.register(loadSettings(settingsFile()).commandBarHotkey);
  const show = (mode: CommandBarMode) => () => commandBar?.show(mode);
  try {
    tray = createTray({
      search: show('search'),
      capture: show('capture'),
      captureClipboard: () => {
        void saveClipboard().then((result) =>
          log.info('tray_clipboard_capture', { ok: result.ok, kind: result.kind }),
        );
      },
      show: showMainWindow,
      quit: () => app.quit(),
      hotkey: () => commandBar?.status.accelerator ?? '',
      extraItems: () => [
        killSwitch.engaged
          ? { label: 'Release kill switch…', click: () => void killSwitch.set(false, 'tray') }
          : {
              label: 'Kill switch: stop all agents',
              accelerator: KILL_SWITCH_HOTKEY,
              registerAccelerator: false,
              click: () => void killSwitch.set(true, 'tray'),
            },
        { type: 'separator' },
      ],
    });
  } catch (err) {
    log.warn('tray_unavailable', { error: err instanceof Error ? err.message : String(err) });
  }
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
      if (!isServableFile(file)) return new Response('Not found', { status: 404 });
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
    const killHotkey = globalShortcut.register(KILL_SWITCH_HOTKEY, () => void killSwitch.set(true, 'hotkey'));
    log[killHotkey ? 'info' : 'warn']('kill_switch_hotkey', {
      accelerator: KILL_SWITCH_HOTKEY,
      registered: killHotkey,
    });
    // The main window gets the CPU first (SPEC §24); the hidden command bar loads once it's up.
    win?.webContents.once('did-finish-load', startCommandBarAndTray);
  });

  let quitting = false;
  app.on('before-quit', (event) => {
    if (quitting) return;
    event.preventDefault();
    quitting = true;
    commandBar?.dispose();
    tray?.destroy();
    void supervisor.stop().finally(() => app.quit());
  });
  app.on('window-all-closed', () => app.quit());
}
