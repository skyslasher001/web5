import { describe, expect, it, vi } from 'vitest';
import { createErrorQueue, type ErrorReport } from './errorQueue';

describe('error report queue', () => {
  it('sends each report once even when flushes overlap', async () => {
    const sent: ErrorReport[] = [];
    let release = (): void => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const queue = createErrorQueue(async (report) => {
      sent.push(report);
      await gate;
      return 201;
    }, vi.fn());
    queue.push({ kind: 'A' });
    queue.push({ kind: 'B' });
    const first = queue.flush();
    const second = queue.flush(); // e.g. a new error arrives while the first flush waits on Core
    release();
    await Promise.all([first, second]);
    expect(sent.map((r) => r.kind)).toEqual(['A', 'B']);
    expect(queue.size).toBe(0);
  });

  it('drops a report Core rejects as invalid instead of blocking the ones behind it', async () => {
    const onRejected = vi.fn();
    const statuses = [422, 201];
    const sent: unknown[] = [];
    const queue = createErrorQueue(async (report) => {
      sent.push(report.kind);
      return statuses.shift() ?? 201;
    }, onRejected);
    queue.push({ kind: 'bad' });
    queue.push({ kind: 'good' });
    await queue.flush();
    expect(sent).toEqual(['bad', 'good']);
    expect(onRejected).toHaveBeenCalledWith(422);
    expect(queue.size).toBe(0);
  });

  it('keeps reports when Core is down or unhealthy, and delivers them later', async () => {
    let mode: 'down' | 'unhealthy' | 'up' = 'down';
    const delivered: unknown[] = [];
    const queue = createErrorQueue(async (report) => {
      if (mode === 'down') throw new Error('ECONNREFUSED');
      if (mode === 'unhealthy') return 503;
      delivered.push(report.kind);
      return 201;
    }, vi.fn());
    queue.push({ kind: 'A' });
    await queue.flush();
    mode = 'unhealthy';
    await queue.flush();
    expect(queue.size).toBe(1);
    mode = 'up';
    await queue.flush();
    expect(delivered).toEqual(['A']);
  });

  it('holds at most `limit` reports', () => {
    const queue = createErrorQueue(async () => 201, vi.fn(), 2);
    for (const kind of ['A', 'B', 'C']) queue.push({ kind });
    expect(queue.size).toBe(2);
  });
});
