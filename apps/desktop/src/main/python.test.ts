import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parsePyvenvHome, resolveBasePython, venvPython } from './python';

describe('python resolution', () => {
  it('parses the venv home line', () => {
    expect(parsePyvenvHome('home = C:\\Python312\r\ninclude-system-site-packages = false\r\n')).toBe(
      'C:\\Python312',
    );
    expect(parsePyvenvHome('version = 3.12\n')).toBeNull();
  });

  it('prefers the interpreter behind the venv and falls back to the venv', () => {
    const cfg = 'home = /opt/py/bin\n';
    const found = resolveBasePython(
      '/repo',
      'linux',
      () => cfg,
      (p) => p === join('/opt/py/bin', 'python3'),
    );
    expect(found).toBe(join('/opt/py/bin', 'python3'));
    const fallback = resolveBasePython(
      '/repo',
      'win32',
      () => null,
      () => false,
    );
    expect(fallback).toBe(venvPython('/repo', 'win32'));
    expect(fallback).toContain(join('.venv', 'Scripts', 'python.exe'));
  });
});
