import { describe, expect, it } from 'vitest';
import { formatBytes, formatDuration, timeAgo } from './format';

describe('format', () => {
  it('bytes', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(16 * 1024 ** 3)).toBe('16 GB');
    expect(formatBytes(null)).toBe('—');
  });

  it('durations and relative time', () => {
    expect(formatDuration(5)).toBe('5s');
    expect(formatDuration(125)).toBe('2m 5s');
    expect(formatDuration(7260)).toBe('2h 1m');
    const now = Date.parse('2026-10-12T10:00:00Z');
    expect(timeAgo('2026-10-12T09:59:55Z', now)).toBe('just now');
    expect(timeAgo('2026-10-12T09:58:00Z', now)).toBe('2m ago');
  });
});
