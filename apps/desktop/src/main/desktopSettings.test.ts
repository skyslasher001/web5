import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { DEFAULT_SETTINGS, isValidAccelerator, loadSettings, saveSettings } from './desktopSettings';

describe('desktop settings', () => {
  it('round-trips and survives a damaged file', () => {
    const file = join(mkdtempSync(join(tmpdir(), 'ds-')), 'desktop-settings.json');
    expect(loadSettings(file)).toEqual(DEFAULT_SETTINGS);
    saveSettings(file, { commandBarHotkey: 'Alt+Space' });
    expect(loadSettings(file).commandBarHotkey).toBe('Alt+Space');
    writeFileSync(file, '{ not json');
    expect(loadSettings(file)).toEqual(DEFAULT_SETTINGS);
  });

  it('accepts modifier+key accelerators only', () => {
    expect(isValidAccelerator('CommandOrControl+Space')).toBe(true);
    expect(isValidAccelerator('Ctrl+Shift+K')).toBe(true);
    expect(isValidAccelerator('Space')).toBe(false); // a bare key would fire while typing anywhere
    expect(isValidAccelerator('Ctrl+Shift')).toBe(false);
    expect(isValidAccelerator('Ctrl++')).toBe(false);
  });
});
