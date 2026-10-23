import type {
  BackupStatus,
  ErrorRecord,
  ForgeProposal,
  ForgeStatus,
  ModelsInfo,
  QueueStats,
} from '@universe/shared-types';
import { describe, expect, it } from 'vitest';
import { backupVital, errorsVital, forgeVital, modelsVital, queueVital, servicesVital } from './vitals';

const NOW = Date.parse('2026-10-14T12:00:00Z');
const hoursAgo = (h: number) => new Date(NOW - h * 3600_000).toISOString();

describe('System Vitals', () => {
  it('services: all running, one down, one failed', () => {
    expect(servicesVital({ core: { state: 'healthy' }, ollama: { state: 'external' } })).toEqual({
      level: 'good',
      text: 'all 2 running',
    });
    expect(servicesVital({ core: { state: 'starting' }, ollama: { state: 'healthy' } }).level).toBe('warn');
    expect(servicesVital({ core: { state: 'failed' }, ollama: { state: 'healthy' } })).toEqual({
      level: 'bad',
      text: 'core failed',
    });
    expect(servicesVital(undefined).level).toBe('off');
  });

  it('models: what Ollama holds in memory, or that it is down', () => {
    const base = { installed: [], assignments: {}, chat_model: null } as unknown as ModelsInfo;
    const up = { reachable: true, url: 'http://127.0.0.1:11434', version: '0.12', error: null };
    expect(modelsVital({ ...base, ollama: { ...up, reachable: false }, loaded: [] }).level).toBe('warn');
    expect(modelsVital({ ...base, ollama: up, loaded: [] }).text).toContain('none in memory');
    const loaded = [{ name: 'qwen3:8b', size_bytes: 5e9, vram_bytes: 5e9, expires_at: null }];
    const text = modelsVital({ ...base, ollama: up, loaded }).text;
    expect(text).toContain('qwen3:8b');
    expect(text).toContain('on the GPU');
  });

  it('queue: idle, busy, paused, dead jobs', () => {
    const q = {
      queued: 0, leased: 0, dead: 0, succeeded_last_hour: 4, by_kind: {}, paused: false,
      pause_reason: null, model_hold: false, workers: 1,
    } as QueueStats; // prettier-ignore
    expect(queueVital(q)).toEqual({ level: 'good', text: 'idle · 4 done in the last hour' });
    expect(queueVital({ ...q, leased: 1, queued: 3 })).toEqual({
      level: 'busy',
      text: '1 running · 3 waiting',
    });
    expect(queueVital({ ...q, paused: true, pause_reason: 'on battery' }).text).toBe('paused: on battery');
    expect(queueVital({ ...q, dead: 2 }).level).toBe('warn');
  });

  it('errors: only unfixed ones from the last day count; critical is red', () => {
    const e = (h: number, over: Partial<ErrorRecord> = {}): ErrorRecord =>
      ({
        id: String(h), fingerprint: 'f', service: 'core', kind: 'ValueError', message: `boom ${h}`, count: 1,
        first_seen: hoursAgo(h), last_seen: hoursAgo(h), severity: 'error', status: 'new', ...over,
      }) as ErrorRecord; // prettier-ignore
    expect(errorsVital([e(30), e(2, { status: 'fixed' })], NOW).level).toBe('good');
    const two = errorsVital([e(5), e(1)], NOW);
    expect(two.level).toBe('warn');
    expect(two.text).toContain('2 in the last 24 hours');
    expect(two.text).toContain('boom 1');
    expect(errorsVital([e(1, { severity: 'critical' })], NOW).level).toBe('bad');
  });

  it('forge: missing, waiting for you, working, idle', () => {
    const s = {
      available: true, reason: null, agent: true, agent_reason: null, sentinel: true, sentinel_reason: null,
      proposals_today: 1, daily_cap: 5, repo: '/r', head: 'abc',
    } as ForgeStatus; // prettier-ignore
    const p = (status: ForgeProposal['status']) => ({ status }) as ForgeProposal;
    expect(forgeVital({ ...s, sentinel: false }, []).text).toContain('not installed');
    expect(forgeVital(s, [p('ready'), p('applied')])).toEqual({ level: 'warn', text: '1 waiting for you' });
    expect(forgeVital(s, [p('verifying')]).level).toBe('busy');
    expect(forgeVital(s, [p('applied')]).text).toBe('idle · 1 of 5 proposals today');
  });

  it('backups: not set up, failed, recent, stale', () => {
    const b = { configured: true, enabled: true, restic_found: true, running: false } as BackupStatus;
    const record = (h: number, status = 'succeeded') =>
      ({ id: 'b', kind: 'scheduled', status, started_at: hoursAgo(h), finished_at: hoursAgo(h) }) as never;
    expect(backupVital({ ...b, configured: false }, NOW).level).toBe('warn');
    expect(backupVital({ ...b, last: record(1, 'failed') }, NOW).level).toBe('bad');
    expect(backupVital({ ...b, last: record(3), last_success: record(3) }, NOW)).toEqual({
      level: 'good',
      text: 'last 3h ago',
    });
    expect(backupVital({ ...b, last: record(72), last_success: record(72) }, NOW).level).toBe('warn');
  });
});
