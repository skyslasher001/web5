import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { buildCsp, contentType, isServableFile, resolveAppFile } from './protocol';

const root = resolve('/srv/ui/dist');

describe('app:// protocol', () => {
  it('maps paths inside the UI build', () => {
    expect(resolveAppFile(root, 'app://universe/')).toBe(join(root, 'index.html'));
    expect(resolveAppFile(root, 'app://universe/assets/index.js')).toBe(join(root, 'assets', 'index.js'));
  });

  it('refuses other hosts and never resolves outside the build folder', () => {
    expect(resolveAppFile(root, 'app://evil/index.html')).toBeNull();
    expect(resolveAppFile(root, 'app://universe/..%2F..%2Fetc%2Fpasswd')).toBeNull();
    // The URL parser collapses encoded dot segments; the result must still be inside root.
    for (const url of ['app://universe/%2e%2e/secret', 'app://universe/a/../../../etc/passwd']) {
      const file = resolveAppFile(root, url);
      expect(file === null || file.startsWith(root + '/') || file.startsWith(root + '\\')).toBe(true);
    }
  });

  it('serves regular files only', () => {
    const dist = mkdtempSync(join(tmpdir(), 'ui-'));
    mkdirSync(join(dist, 'assets'));
    writeFileSync(join(dist, 'index.html'), '<!doctype html>');
    expect(isServableFile(resolveAppFile(dist, 'app://universe/'))).toBe(true);
    expect(isServableFile(resolveAppFile(dist, 'app://universe/assets'))).toBe(false); // a directory
    expect(isServableFile(resolveAppFile(dist, 'app://universe/missing.js'))).toBe(false);
    expect(isServableFile(resolveAppFile(dist, 'app://evil/index.html'))).toBe(false);
  });

  it('serves a strict CSP that only reaches Core on loopback', () => {
    const csp = buildCsp(47821);
    expect(csp).toContain("script-src 'self'");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:47821 ws://127.0.0.1:47821");
    expect(csp).not.toContain('unsafe-eval');
    expect(csp).toContain("media-src 'self' blob:"); // viewers play files Core sends with the session token
    expect(contentType('a.woff2')).toBe('font/woff2');
  });
});
