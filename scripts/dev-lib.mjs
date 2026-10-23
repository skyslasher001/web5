// Helpers for scripts/dev.mjs, kept apart so they can be tested.

/** Load .env text into env. The environment wins; an empty value (`KEY=`, here or there) counts as unset. */
export function applyDotEnv(text, env) {
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const [rawKey, ...rest] = line.split('=');
    const key = rawKey.trim();
    const value = rest
      .join('=')
      .trim()
      .replace(/^["']|["']$/g, '');
    if (value && !env[key]) env[key] = value;
  }
}

/**
 * How to stop a child and everything it started, or null when child.kill() does. On Windows a child spawned
 * with shell: true is cmd.exe: killing it alone leaves Vite running and holding its port. (Electron is spawned
 * directly and gets child.kill(), so the supervisor still sees its parent go and stops Core cleanly.)
 */
export function killCommand(pid, platform, viaShell) {
  if (platform !== 'win32' || !viaShell || pid === undefined) return null;
  return ['taskkill', ['/PID', String(pid), '/T', '/F']];
}
