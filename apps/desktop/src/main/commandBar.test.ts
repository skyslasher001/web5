import { beforeEach, describe, expect, it, vi } from 'vitest';

// Fake globalShortcut (another app owns some accelerators) and BrowserWindow (events fired by hand).
const fake = vi.hoisted(() => ({
  owned: new Set<string>(), // accelerators that another app holds
  mine: new Set<string>(),
  windows: [] as Array<{
    destroyed: boolean;
    handlers: Map<string, (...args: unknown[]) => void>;
    contentsHandlers: Map<string, (...args: unknown[]) => void>;
  }>,
}));

vi.mock('electron', () => {
  class BrowserWindow {
    destroyed = false;
    handlers = new Map<string, (...args: unknown[]) => void>();
    contentsHandlers = new Map<string, (...args: unknown[]) => void>();
    webContents = {
      setWindowOpenHandler: () => {},
      on: (event: string, handler: (...args: unknown[]) => void) => this.contentsHandlers.set(event, handler),
      isDevToolsOpened: () => false,
      send: () => {},
    };
    constructor() {
      fake.windows.push(this);
    }
    setAlwaysOnTop(): void {}
    on(event: string, handler: (...args: unknown[]) => void): void {
      this.handlers.set(event, handler);
    }
    loadURL(): Promise<void> {
      return Promise.resolve();
    }
    isDestroyed(): boolean {
      return this.destroyed;
    }
    destroy(): void {
      this.destroyed = true;
      this.handlers.get('closed')?.();
    }
    isVisible(): boolean {
      return false;
    }
    getSize(): number[] {
      return [680, 460];
    }
    setPosition(): void {}
    show(): void {}
    focus(): void {}
    hide(): void {}
  }
  return {
    BrowserWindow,
    globalShortcut: {
      register: (accelerator: string) => {
        if (fake.owned.has(accelerator)) return false;
        fake.mine.add(accelerator);
        return true;
      },
      unregister: (accelerator: string) => fake.mine.delete(accelerator),
      unregisterAll: () => fake.mine.clear(),
    },
    screen: {
      getCursorScreenPoint: () => ({ x: 0, y: 0 }),
      getDisplayNearestPoint: () => ({ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }),
    },
  };
});

import { CommandBar } from './commandBar';

const log = { info: () => {}, warn: () => {}, error: () => {} };
const bar = () =>
  new CommandBar({
    preload: 'preload.cjs',
    url: 'app://universe/#command-bar',
    log: log as never,
    isAllowedNavigation: () => true,
  });

describe('command bar', () => {
  beforeEach(() => {
    fake.owned.clear();
    fake.mine.clear();
    fake.windows.length = 0;
  });

  it('keeps the working shortcut when the new one is taken', () => {
    const commandBar = bar();
    expect(commandBar.register('Ctrl+Shift+Space').registered).toBe(true);
    fake.owned.add('Ctrl+Alt+K');
    const status = commandBar.register('Ctrl+Alt+K');
    expect(status.registered).toBe(false);
    expect(status.error).toContain('already used');
    expect([...fake.mine]).toEqual(['Ctrl+Shift+Space']); // the old one still works
    expect(commandBar.status).toMatchObject({ accelerator: 'Ctrl+Shift+Space', registered: true });

    expect(commandBar.register('Ctrl+Alt+J').registered).toBe(true);
    expect([...fake.mine]).toEqual(['Ctrl+Alt+J']); // the old one is released once the new one works
    expect(commandBar.register('Ctrl+Alt+J').registered).toBe(true); // registering the same one again is fine
    expect([...fake.mine]).toEqual(['Ctrl+Alt+J']);
  });

  it.each([
    ['render-process-gone', [{}, { reason: 'crashed', exitCode: 1 }]],
    ['did-fail-load', [{}, -102, 'ERR_CONNECTION_REFUSED', 'app://universe/#command-bar', true]],
  ])('recreates the window after %s', (event, args) => {
    const commandBar = bar();
    commandBar.create();
    const first = fake.windows[0]!;
    first.contentsHandlers.get(event)?.(...args);
    expect(first.destroyed).toBe(true);
    expect(commandBar.window).toBeNull();
    commandBar.show();
    expect(fake.windows).toHaveLength(2);
    expect(commandBar.window).toBe(fake.windows[1]);
  });
});
