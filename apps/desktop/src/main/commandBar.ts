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
      this.win = null;
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
  register(accelerator: string): HotkeyStatus {
    if (this.hotkey.registered && this.hotkey.accelerator) globalShortcut.unregister(this.hotkey.accelerator);
    let registered = false;
    let error: string | null = null;
    try {
      registered = globalShortcut.register(accelerator, () => this.toggle('search'));
      if (!registered) error = `${accelerator} is already used by another app; choose a different shortcut.`;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
    this.hotkey = { accelerator, registered, error };
    this.opts.log[registered ? 'info' : 'warn']('command_bar_hotkey', { accelerator, registered, error });
    return this.hotkey;
  }

  get status(): HotkeyStatus {
    return this.hotkey;
  }

  dispose(): void {
    globalShortcut.unregisterAll();
    if (this.win && !this.win.isDestroyed()) this.win.destroy();
  }
}
