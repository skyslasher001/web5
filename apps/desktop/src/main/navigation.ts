// Which URLs the window may navigate to (renderer-initiated navigations only; main loads the rest).
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

export interface NavigationRules {
  /** Vite dev server URL in `pnpm dev`; undefined when serving the built UI. */
  devUiUrl?: string;
  /** Directory holding the static safe-mode page. */
  safeModeDir: string;
}

export function isAllowedNavigation(url: string, rules: NavigationRules): boolean {
  let target: URL;
  try {
    target = new URL(url);
  } catch {
    return false;
  }
  if (target.protocol === 'app:') return target.host === 'universe';
  if (target.protocol === 'file:') {
    // Only the safe-mode page itself, never any other file on disk.
    return target.pathname === pathToFileURL(join(rules.safeModeDir, 'index.html')).pathname;
  }
  if (rules.devUiUrl) {
    try {
      return target.origin === new URL(rules.devUiUrl).origin; // exact origin, not a string prefix
    } catch {
      return false;
    }
  }
  return false;
}
