// Small settings owned by Electron main (they matter before Core is up), kept in userData/desktop-settings.json.
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

export interface DesktopSettings {
  commandBarHotkey: string;
}

export const DEFAULT_SETTINGS: DesktopSettings = {
  commandBarHotkey: 'CommandOrControl+Space',
};

export function loadSettings(file: string): DesktopSettings {
  if (!existsSync(file)) return { ...DEFAULT_SETTINGS };
  try {
    const raw = JSON.parse(readFileSync(file, 'utf8')) as Partial<DesktopSettings>;
    return {
      commandBarHotkey:
        typeof raw.commandBarHotkey === 'string' && raw.commandBarHotkey.trim()
          ? raw.commandBarHotkey.trim()
          : DEFAULT_SETTINGS.commandBarHotkey,
    };
  } catch {
    return { ...DEFAULT_SETTINGS }; // a damaged file never blocks startup
  }
}

export function saveSettings(file: string, settings: DesktopSettings): void {
  mkdirSync(dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, JSON.stringify(settings, null, 2));
  renameSync(tmp, file);
}

/** Electron accelerators: modifiers plus one key, e.g. "CommandOrControl+Shift+Space". */
export function isValidAccelerator(value: string): boolean {
  const parts = value.split('+').map((p) => p.trim());
  if (parts.length < 2 || parts.some((p) => !p)) return false;
  const modifiers = new Set([
    'Command',
    'Cmd',
    'Control',
    'Ctrl',
    'CommandOrControl',
    'CmdOrCtrl',
    'Alt',
    'Option',
    'AltGr',
    'Shift',
    'Super',
    'Meta',
  ]);
  const key = parts[parts.length - 1]!;
  return parts.slice(0, -1).every((p) => modifiers.has(p)) && !modifiers.has(key) && /^[\w]+$/.test(key);
}
