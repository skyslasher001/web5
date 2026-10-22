// The command bar (ARCHITECTURE.md §6.4): a frameless always-on-top window created once and kept hidden,
// so the global hotkey only has to show() it (< 150 ms budget), over any app, even when UNIVERSE is minimized.
import { BrowserWindow, globalShortcut, screen } from 'electron';
import type { HotkeyStatus } from '@universe/shared-types';
import { CH } from './channels';
import type { Logger } from './logger';

export type CommandBarMode = 'search' | 'capture';

export class CommandBar {
  private win: BrowserWindow | null = null;
  private hotkey: HotkeyStatus = { accelerator: '', registered: false, error: null };

  constructor(
    private readonly opts: {
      preload: string;
      url: string;
      log: Logger;
      isAllowedNavigation: (url: string) => boolean;
    },
  ) {}

  create(): void {
    if (this.win && !this.win.isDestroyed()) return;
    const win = new BrowserWindow({
      width: 680,
      height: 460,
      show: false,
      frame: false,
      resizable: false,
      movable: true,
      minimizable: false,
      maximizable: false,
      fullscreenable: false,
      skipTaskbar: true,
      alwaysOnTop: true,
      title: 'UNIVERSE command bar',
      backgroundColor: '#0A0F1C',
      webPreferences: {
        preload: this.opts.preload,
        contextIsolation: true,
        sandbox: true,
        nodeIntegration: false,
        webSecurity: true,
        spellcheck: false,
      },
    });
    win.setAlwaysOnTop(true, 'floating');
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (event, url) => {
      if (!this.opts.isAllowedNavigation(url)) event.preventDefault();
    });
    win.on('blur', () => {
      if (!win.webContents.isDevToolsOpened()) win.hide();
    });
    win.on('closed', () => {
      if (this.win === win) this.win = null;
    });
    // A crashed or failed page would leave a blank bar: drop the window, so the next show() makes a new one.
    const discard = (event: string, details: Record<string, unknown>) => {
      this.opts.log.warn('command_bar_window_lost', { event, ...details });
      if (this.win === win) this.win = null;
      if (!win.isDestroyed()) win.destroy();
    };
    win.webContents.on('render-process-gone', (_event, details) =>
      discard('render-process-gone', { ...details }),
    );
    win.webContents.on('did-fail-load', (_event, code, description, _url, isMainFrame) => {
      if (isMainFrame && code !== -3) discard('did-fail-load', { code, description }); // -3: aborted, not failed
    });
    void win.loadURL(this.opts.url);
    this.win = win;
  }

  get window(): BrowserWindow | null {
    return this.win;
  }

  get visible(): boolean {
    return !!this.win && !this.win.isDestroyed() && this.win.isVisible();
  }

  show(mode: CommandBarMode = 'search'): void {
    this.create();
    const win = this.win;
    if (!win) return;
    // Centre it in the upper third of the display the pointer is on.
    const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
    const { x, y, width, height } = display.workArea;
    const [w] = win.getSize();
    win.setPosition(Math.round(x + (width - (w ?? 680)) / 2), Math.round(y + height * 0.18));
    win.show();
    win.focus();
    win.webContents.send(CH.commandBarShow, mode);
  }

  hide(): void {
    if (this.win && !this.win.isDestroyed()) this.win.hide();
  }

  toggle(mode: CommandBarMode = 'search'): void {
    if (this.visible) this.hide();
    else this.show(mode);
  }

  /** Register the global shortcut. A failure (another app owns it) is reported, never fatal. */
  /** The new shortcut is registered before the old one is released, so a failure keeps the one that works. */
  register(accelerator: string): HotkeyStatus {
    const previous = this.hotkey;
    if (previous.registered && previous.accelerator === accelerator) return previous;
    let registered = false;
    let error: string | null = null;
    try {
      registered = globalShortcut.register(accelerator, () => this.toggle('search'));
      if (!registered) error = `${accelerator} is already used by another app; choose a different shortcut.`;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
    this.opts.log[registered ? 'info' : 'warn']('command_bar_hotkey', { accelerator, registered, error });
    const attempt = { accelerator, registered, error };
    if (!registered && previous.registered) {
      // Report the failed attempt, but keep the working shortcut as the status.
      return { ...attempt, error: `${error} ${previous.accelerator} still works.` };
    }
    if (registered && previous.registered && previous.accelerator)
      globalShortcut.unregister(previous.accelerator);
    this.hotkey = attempt;
    return attempt;
  }

  get status(): HotkeyStatus {
    return this.hotkey;
  }

  dispose(): void {
    globalShortcut.unregisterAll();
    if (this.win && !this.win.isDestroyed()) this.win.destroy();
  }
}
