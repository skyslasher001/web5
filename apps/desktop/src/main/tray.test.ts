import { beforeEach, describe, expect, it, vi } from 'vitest';

// A fake Tray and Menu: the template given to the last setContextMenu is what the owner sees.
const fake = vi.hoisted(() => ({ menus: [] as Array<Array<{ label?: string }>>, events: [] as string[] }));

vi.mock('electron', () => {
  class Tray {
    setToolTip(): void {}
    setContextMenu(menu: Array<{ label?: string }>): void {
      fake.menus.push(menu);
    }
    on(event: string): void {
      fake.events.push(event);
    }
  }
  const image = { resize: () => image };
  return {
    Tray,
    Menu: { buildFromTemplate: (template: Array<{ label?: string }>) => template },
    nativeImage: { createFromBitmap: () => image },
  };
});

import { createTray } from './tray';

const labels = () => (fake.menus.at(-1) ?? []).map((item) => item.label).filter(Boolean);

describe('tray menu', () => {
  beforeEach(() => {
    fake.menus.length = 0;
    fake.events.length = 0;
  });

  it('shows state changes without waiting for a right-click (Linux and Windows never send one)', () => {
    let mic = false;
    let hotkey = 'Ctrl+Shift+Space';
    const noop = () => {};
    const tray = createTray({
      search: noop,
      capture: noop,
      captureClipboard: noop,
      show: noop,
      quit: noop,
      hotkey: () => hotkey,
      extraItems: () => (mic ? [{ label: 'Microphone on: turn it off' }] : []),
    });
    expect(labels()).not.toContain('Microphone on: turn it off');

    mic = true;
    tray.rebuild();
    expect(labels()).toContain('Microphone on: turn it off');

    hotkey = 'Ctrl+Alt+K';
    tray.rebuild();
    expect(fake.menus.at(-1)?.[0]).toMatchObject({ label: 'Quick search', accelerator: 'Ctrl+Alt+K' });
  });
});
