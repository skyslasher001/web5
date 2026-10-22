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
import { MicConsent, mediaAllowed } from './protected/consent';
import { KILL_SWITCH_HOTKEY, KillSwitchControl, readKillSwitchFile } from './protected/killswitch';
import { ForgeControl } from './protected/forge';
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
  forge.coreState(core);
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
  // A new page (reload, crash, safe mode) starts with the mic off: consent goes with the page that had it.
  win.webContents.on('did-navigate', () => consent.revoke('window'));
  win.webContents.on('render-process-gone', (_e, details) => {
    consent.revoke('window');
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
  // ---------- Forge releases (protected control: native dialog, then the supervisor) ----------
  ipcMain.handle(CH.forgeApprove, (_e, id: unknown) =>
    typeof id === 'string' ? forge.approve(id) : { ok: false, message: 'Bad proposal id' },
  );
  ipcMain.handle(CH.forgeRollback, (_e, tag: unknown) =>
    typeof tag === 'string' ? forge.rollback(tag) : { ok: false, message: 'Bad release' },
  );
  ipcMain.handle(CH.getReleases, () =>
    forge.releases().catch((err: unknown) => ({ available: false, reason: String(err), releases: [] })),
  );

  // ---------- consent (protected: ./protected/consent.ts) ----------
  ipcMain.handle(CH.getConsent, () => consent.state());
  ipcMain.handle(CH.setMicConsent, (e, on: unknown) => {
    if (typeof on !== 'boolean') return consent.state();
    // Only the main window may ask, and asking to turn it on still shows the native dialog.
    if (on && e.sender !== win?.webContents)
      return consent.state('Only the main window can turn the mic on.');
    return consent.request(on, 'hud');
  });

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
    tray?.rebuild(); // the Quick search item shows the shortcut
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

const forge = new ForgeControl({
  core: async (method, path, body) => {
    const response = await net.fetch(`${coreUrl}/api/v1${path}`, {
      method,
      headers: { Authorization: `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`Core ${path}: HTTP ${response.status}`);
    return (await response.json()) as never;
  },
  applyRelease: (body) => supervisor.applyRelease(body),
  rollbackRelease: (tag) => supervisor.rollbackRelease(tag),
  listReleases: () => supervisor.listReleases(),
  confirm: async ({ title, message, detail, confirmLabel }) => {
    const parent = BrowserWindow.getFocusedWindow() ?? undefined;
    const options = {
      type: 'warning' as const,
      title,
      message,
      detail,
      buttons: ['Cancel', confirmLabel],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    };
    const { response } = parent
      ? await dialog.showMessageBox(parent, options)
      : await dialog.showMessageBox(options);
    return response === 1;
  },
  log: (event, fields) => log.info(event, fields),
});

const consent = new MicConsent({
  confirm: async () => {
    const options = {
      type: 'question' as const,
      buttons: ['Keep it off', 'Turn on the microphone'],
      defaultId: 0,
      cancelId: 0,
      title: 'Turn on the microphone?',
      message: 'Turn on the microphone?',
      detail:
        'UNIVERSE will listen while the mic is on. What you say is processed on this computer and never stored, ' +
        'unless you save a voice memo. Turn it off any time from the orb, the tray or the kill switch. ' +
        'It is off again the next time UNIVERSE starts.',
    };
    const choice = win ? await dialog.showMessageBox(win, options) : await dialog.showMessageBox(options);
    return choice.response === 1;
  },
  killSwitchEngaged: () => killSwitch.engaged,
  onChange: (state) => {
    for (const w of BrowserWindow.getAllWindows()) w.webContents.send(CH.consentEvent, state);
    tray?.tray.setToolTip(state.mic ? 'UNIVERSE · microphone on' : 'UNIVERSE'); // main's own indicator
    tray?.rebuild(); // shows or hides "Microphone on: turn it off"
  },
  record: async (mic, via) => {
    const response = await net.fetch(`${coreUrl}/api/v1/consent`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${sessionToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'mic', on: mic, via }),
    });
    if (!response.ok) throw new Error(`Core answered ${response.status}`);
  },
  log: (event, fields) => log.info(event, fields),
});

const killSwitch = new KillSwitchControl({
  initial: readKillSwitchFile(join(paths.dataDir, 'killswitch.json')),
  setOnSupervisor: (engaged) => supervisor.setKillSwitch(engaged),
  stopCapture: () => {
    // Chromium keeps an open stream running even after permission is revoked: if the mic was on, reload the
    // page, which ends every capture it holds. Then tell any window (the reload already did for the main one).
    if (consent.revoke('killswitch') && win && !win.isDestroyed()) win.webContents.reload();
  },
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
    tray?.rebuild(); // swaps "Kill switch: stop all agents" for "Release kill switch…"
  },
  log: (event, fields) => log.warn(event, fields),
});

let commandBar: CommandBar | null = null;
let tray: ReturnType<typeof createTray> | null = null;

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
        ...(consent.mic
          ? [
              {
                label: 'Microphone on: turn it off',
                // From outside the page: don't rely on it to stop its stream. A reload ends every capture.
                click: () => {
                  if (consent.revoke('tray') && win && !win.isDestroyed()) win.webContents.reload();
                },
              },
            ]
          : []),
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
    // The mic: audio only, for our main window, while you've consented (protected/consent.ts). Camera, screen,
    // notifications…: denied (screen and camera consent arrive in Phase 8).
    const appOrigins = ['app://universe', ...(devUiUrl ? [new URL(devUiUrl).origin] : [])];
    session.defaultSession.setPermissionRequestHandler((wc, permission, callback, details) => {
      if (permission === 'clipboard-sanitized-write') return callback(true);
      const mediaTypes = 'mediaTypes' in details ? (details.mediaTypes ?? []) : [];
      const request = {
        permission,
        mediaTypes,
        requestingUrl: details.requestingUrl ?? wc.getURL(),
        fromMainWindow: wc === win?.webContents,
      };
      const allowed = mediaAllowed(request, consent.mic, appOrigins);
      if (permission === 'media') log.info('media_permission', { mediaTypes, allowed });
      callback(allowed);
    });
    session.defaultSession.setPermissionCheckHandler((wc, permission, requestingOrigin, details) => {
      if (permission === 'clipboard-sanitized-write') return true;
      const request = {
        permission,
        mediaTypes: details.mediaType ? [details.mediaType] : [],
        requestingUrl: details.requestingUrl ?? requestingOrigin,
        fromMainWindow: wc !== null && wc === win?.webContents,
      };
      return mediaAllowed(request, consent.mic, appOrigins);
    });
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
    tray?.tray.destroy();
    void supervisor.stop().finally(() => app.quit());
  });
  app.on('window-all-closed', () => app.quit());
}
