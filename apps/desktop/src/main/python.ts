// Locates the Python interpreters. Pure functions so they can be unit-tested without Electron.
import { join } from 'node:path';

export function venvPython(repoRoot: string, platform: NodeJS.Platform): string {
  return platform === 'win32'
    ? join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : join(repoRoot, '.venv', 'bin', 'python');
}

export function parsePyvenvHome(cfg: string): string | null {
  for (const line of cfg.split(/\r?\n/)) {
    const match = /^\s*home\s*=\s*(.+?)\s*$/.exec(line);
    if (match?.[1]) return match[1];
  }
  return null;
}

/**
 * The supervisor runs on the interpreter *behind* the venv (`-I -S`, stdlib only), so a broken
 * dependency upgrade inside the venv can't take the watchdog down (ADR-0001).
 */
export function resolveBasePython(
  repoRoot: string,
  platform: NodeJS.Platform,
  readFile: (path: string) => string | null,
  exists: (path: string) => boolean,
): string {
  const cfg = readFile(join(repoRoot, '.venv', 'pyvenv.cfg'));
  const home = cfg ? parsePyvenvHome(cfg) : null;
  if (home) {
    const names = platform === 'win32' ? ['python.exe'] : ['python3', 'python'];
    for (const name of names) {
      const candidate = join(home, name);
      if (exists(candidate)) return candidate;
    }
  }
  return venvPython(repoRoot, platform);
}
