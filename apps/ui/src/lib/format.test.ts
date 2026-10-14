import { describe, expect, it } from 'vitest';
import { agentStatsLine, formatAccelerator, formatBytes, formatDuration, timeAgo } from './format';

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

  it('shows shortcuts the way people read them', () => {
    expect(formatAccelerator('CommandOrControl+Space')).toBe('Ctrl+Space');
    expect(formatAccelerator('CmdOrCtrl+Shift+K')).toBe('Ctrl+Shift+K');
    expect(formatAccelerator('Alt+F1')).toBe('Alt+F1');
  });
});

describe('agent stats', () => {
  const none = {
    tasks: 0,
    done: 0,
    failed: 0,
    cancelled: 0,
    success_rate: null,
    tokens_in: 0,
    tokens_out: 0,
    cost_usd: 0,
    avg_steps: null,
    last_active: null,
  };
  it('summarize an agent in one line', () => {
    expect(agentStatsLine(none)).toBe('No tasks yet');
    const now = Date.parse('2026-10-14T12:00:00Z');
    const busy = {
      ...none,
      tasks: 4,
      done: 3,
      failed: 1,
      success_rate: 0.75,
      avg_steps: 3.5,
      tokens_in: 1800,
      tokens_out: 700,
      last_active: '2026-10-14T11:00:00Z',
    };
    expect(agentStatsLine(busy, now)).toBe(
      '4 tasks · 75% succeeded · 3.5 steps avg · 2.5k tokens · last 1h ago',
    );
    expect(agentStatsLine({ ...none, tasks: 1 }, now)).toBe('1 task');
  });
});
