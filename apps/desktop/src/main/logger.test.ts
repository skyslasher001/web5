import { existsSync, mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { createLogger } from './logger';

describe('desktop logger', () => {
  it('redacts secrets and rotates when the file grows past the limit', () => {
    const file = join(mkdtempSync(join(tmpdir(), 'log-')), 'desktop.jsonl');
    const log = createLogger(file, ['s3cret-token-value'], 300);
    for (let i = 0; i < 10; i++) log.info('tick', { i, header: 'Bearer s3cret-token-value' });
    expect(existsSync(`${file}.1`)).toBe(true);
    const text = readFileSync(file, 'utf8') + readFileSync(`${file}.1`, 'utf8');
    expect(text).not.toContain('s3cret-token-value');
    expect(text).toContain('[redacted]');
    expect(readFileSync(file, 'utf8').length).toBeLessThan(600);
  });
});
