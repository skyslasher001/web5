import { describe, expect, it } from 'vitest';
import { parseSupervisorLine, restartDelayMs } from './supervisor';

describe('supervisor protocol', () => {
  it('parses ready and status lines and ignores anything else', () => {
    expect(
      parseSupervisorLine('{"event":"ready","control_port":5000,"core_url":"http://127.0.0.1:1"}'),
    ).toMatchObject({
      event: 'ready',
      control_port: 5000,
    });
    expect(parseSupervisorLine('{"event":"status","status":{"services":{}}}')?.event).toBe('status');
    expect(parseSupervisorLine('Traceback (most recent call last):')).toBeNull();
    expect(parseSupervisorLine('{"event":"ready"}')).toBeNull();
    expect(parseSupervisorLine('null')).toBeNull();
  });

  it('backs off restarts up to 30 seconds', () => {
    expect([1, 2, 3, 6, 20].map(restartDelayMs)).toEqual([1000, 2000, 4000, 30000, 30000]);
  });
});
