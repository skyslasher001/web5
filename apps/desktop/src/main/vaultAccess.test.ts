import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { insideFolder } from './vaultAccess';

const vault = resolve('/data/vault');

describe('vault access', () => {
  it('allows files inside the vault only', () => {
    expect(insideFolder(vault, join(vault, 'notes', '2026', '10', 'a.md'))).toBe(true);
    expect(insideFolder(vault, vault)).toBe(false); // the folder itself is not a file to open
    expect(insideFolder(vault, resolve('/data/vault-other/x.txt'))).toBe(false); // a sibling with the same prefix
    expect(insideFolder(vault, join(vault, '..', 'secrets.txt'))).toBe(false);
    expect(insideFolder(vault, 'notes/a.md')).toBe(false); // relative paths are refused
  });

  it('allows names that merely start with two dots', () => {
    expect(insideFolder(vault, join(vault, '..notes.md'))).toBe(true);
    expect(insideFolder(vault, join(vault, '...', 'a.md'))).toBe(true);
    expect(insideFolder(vault, join(vault, '..', 'vault-other', 'a.md'))).toBe(false);
  });

  describe('through a link', () => {
    let tmp = '';
    afterEach(() => {
      if (tmp) rmSync(tmp, { recursive: true, force: true });
      tmp = '';
    });

    it('matches the resolved path Core sends against a vault path that goes through a link', () => {
      tmp = mkdtempSync(join(tmpdir(), 'universe-vault-access-'));
      const real = join(tmp, 'real-vault');
      mkdirSync(join(real, 'notes'), { recursive: true });
      writeFileSync(join(real, 'notes', 'a.md'), 'x');
      const linked = join(tmp, 'linked-vault');
      symlinkSync(real, linked, 'junction'); // 'junction' is ignored off Windows
      // The settings hold the link; Core resolves the vault and sends real paths (and the other way round).
      expect(insideFolder(linked, join(real, 'notes', 'a.md'))).toBe(true);
      expect(insideFolder(real, join(linked, 'notes', 'a.md'))).toBe(true);
      // A file that doesn't exist (any more) still resolves through its existing parent.
      expect(insideFolder(linked, join(real, 'notes', 'gone.md'))).toBe(true);
      // Resolving never lets a path outside the vault in.
      mkdirSync(join(tmp, 'outside'));
      expect(insideFolder(linked, join(tmp, 'outside', 'secret.txt'))).toBe(false);
      expect(insideFolder(linked, join(linked, '..', 'outside', 'secret.txt'))).toBe(false);
    });
  });
});
