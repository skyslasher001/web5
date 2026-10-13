import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
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
});
