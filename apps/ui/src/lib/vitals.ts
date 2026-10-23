// System Vitals (SPEC §20, Phase 5): one line and a colour for each part of Core's heartbeat.
import type {
  BackupStatus,
  ErrorRecord,
  ForgeProposal,
  ForgeStatus,
  ModelsInfo,
  QueueStats,
} from '@universe/shared-types';
import { formatBytes, timeAgo } from './format';

export type VitalLevel = 'good' | 'busy' | 'warn' | 'bad' | 'off';

export interface Vital {
  level: VitalLevel;
  text: string;
}

const DAY_MS = 24 * 3600_000;

export function servicesVital(services: Record<string, { state: string }> | undefined): Vital {
  if (!services) return { level: 'off', text: 'waiting for the supervisor' };
  const entries = Object.entries(services).filter(([, s]) => s.state !== 'stopped');
  const up = entries.filter(([, s]) => s.state === 'healthy' || s.state === 'external');
  const failed = entries.find(([, s]) => s.state === 'failed');
  if (failed) return { level: 'bad', text: `${failed[0]} failed` };
  if (up.length === entries.length) return { level: 'good', text: `all ${entries.length} running` };
  const down = entries.find(([, s]) => s.state !== 'healthy' && s.state !== 'external')!;
  return { level: 'warn', text: `${down[0]} ${down[1].state} · ${up.length} of ${entries.length} running` };
}

export function modelsVital(models: ModelsInfo | undefined): Vital {
  if (!models) return { level: 'off', text: '…' };
  if (!models.ollama.reachable) return { level: 'warn', text: 'Ollama is not running' };
  if (models.loaded.length === 0) return { level: 'good', text: 'none in memory (they load on use)' };
  const vram = models.loaded.reduce((sum, m) => sum + m.vram_bytes, 0);
  const names = models.loaded.map((m) => m.name).join(', ');
  return { level: 'good', text: `${names}${vram ? ` · ${formatBytes(vram)} on the GPU` : ''}` };
}

export function queueVital(q: QueueStats | undefined): Vital {
  if (!q) return { level: 'off', text: '…' };
  if (q.dead > 0) return { level: 'warn', text: `${q.dead} failed for good · ${q.queued} waiting` };
  if (q.paused) return { level: 'warn', text: `paused${q.pause_reason ? `: ${q.pause_reason}` : ''}` };
  if (q.leased || q.queued) return { level: 'busy', text: `${q.leased} running · ${q.queued} waiting` };
  return { level: 'good', text: `idle · ${q.succeeded_last_hour} done in the last hour` };
}

export function errorsVital(errors: ErrorRecord[] | undefined, now: number = Date.now()): Vital {
  if (!errors) return { level: 'off', text: '…' };
  const recent = errors.filter((e) => e.status !== 'fixed' && now - Date.parse(e.last_seen) < DAY_MS);
  if (recent.length === 0) return { level: 'good', text: 'none in the last 24 hours' };
  const worst = recent.some((e) => e.severity === 'critical') ? 'bad' : 'warn';
  const latest = recent.reduce((a, b) => (Date.parse(a.last_seen) >= Date.parse(b.last_seen) ? a : b));
  return {
    level: worst,
    text: `${recent.length} in the last 24 hours · latest: ${latest.message.slice(0, 80)} (${timeAgo(latest.last_seen, now)})`,
  };
}

export function forgeVital(status: ForgeStatus | undefined, proposals: ForgeProposal[] | undefined): Vital {
  if (!status) return { level: 'off', text: '…' };
  if (!status.agent || !status.sentinel) return { level: 'off', text: 'not installed (Phase 5 patch)' };
  if (!status.available) return { level: 'off', text: 'no codebase set (UNIVERSE_REPO_DIR)' };
  const all = proposals ?? [];
  const waiting = all.filter((p) => p.status === 'ready').length;
  const working = all.filter((p) => p.status === 'draft' || p.status === 'verifying').length;
  if (waiting) return { level: 'warn', text: `${waiting} waiting for you` };
  if (working) return { level: 'busy', text: `working on ${working}` };
  return { level: 'good', text: `idle · ${status.proposals_today} of ${status.daily_cap} proposals today` };
}

export function backupVital(b: BackupStatus | undefined, now: number = Date.now()): Vital {
  if (!b) return { level: 'off', text: '…' };
  if (!b.configured) return { level: 'warn', text: 'not set up (Vault → Backups)' };
  if (b.running) return { level: 'busy', text: 'backing up now' };
  if (b.last?.status === 'failed')
    return { level: 'bad', text: `last backup failed: ${b.last.error ?? 'see Vault'}` };
  const done = b.last_success?.finished_at ?? b.last_success?.started_at;
  if (!done) return { level: 'warn', text: 'no backup yet' };
  const stale = now - Date.parse(done) > 2 * DAY_MS;
  return {
    level: stale ? 'warn' : 'good',
    text: `last ${timeAgo(done, now)}${b.enabled ? '' : ' · schedule off'}`,
  };
}
