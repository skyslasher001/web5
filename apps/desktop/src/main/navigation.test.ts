import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { describe, expect, it } from 'vitest';
import { isAllowedNavigation } from './navigation';

const safeModeDir = resolve('/app/dist/safe-mode');
const safePage = pathToFileURL(join(safeModeDir, 'index.html')).href;

describe('navigation allowlist', () => {
  it('allows the app, the safe-mode page and the dev server origin', () => {
    expect(isAllowedNavigation('app://universe/index.html', { safeModeDir })).toBe(true);
    expect(isAllowedNavigation(`${safePage}?reason=core-failed`, { safeModeDir })).toBe(true);
    expect(
      isAllowedNavigation('http://127.0.0.1:5173/x', { safeModeDir, devUiUrl: 'http://127.0.0.1:5173' }),
    ).toBe(true);
  });

  it('refuses other files, look-alike origins and the web', () => {
    expect(isAllowedNavigation(pathToFileURL(resolve('/etc/passwd')).href, { safeModeDir })).toBe(false);
    expect(isAllowedNavigation(pathToFileURL(join(safeModeDir, 'other.html')).href, { safeModeDir })).toBe(
      false,
    );
    expect(
      isAllowedNavigation('http://127.0.0.1:51730/', { safeModeDir, devUiUrl: 'http://127.0.0.1:5173' }),
    ).toBe(false);
    expect(isAllowedNavigation('app://evil/index.html', { safeModeDir })).toBe(false);
    expect(isAllowedNavigation('https://example.com', { safeModeDir })).toBe(false);
    expect(isAllowedNavigation('http://127.0.0.1:5173/', { safeModeDir })).toBe(false); // not in dev mode
    expect(isAllowedNavigation('not a url', { safeModeDir })).toBe(false);
  });
});
