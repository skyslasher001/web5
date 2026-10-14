import type { AgentProfile } from '@universe/shared-types';

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (seconds < 10) return 'just now';
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

/** An Electron accelerator as people read it ("CommandOrControl+Space" → "Ctrl+Space"). */
export function formatAccelerator(accelerator: string): string {
  return accelerator
    .split('+')
    .map(
      (key) => ({ CommandOrControl: 'Ctrl', CmdOrCtrl: 'Ctrl', Control: 'Ctrl', Option: 'Alt' })[key] ?? key,
    )
    .join('+');
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

/** One line of stats: tasks, success rate, average steps, tokens, last active. */
export function agentStatsLine(s: AgentProfile['stats'], now = Date.now()): string {
  if (!s.tasks) return 'No tasks yet';
  const parts = [`${s.tasks} task${s.tasks === 1 ? '' : 's'}`];
  if (s.success_rate !== null) parts.push(`${Math.round(s.success_rate * 100)}% succeeded`);
  if (s.avg_steps !== null) parts.push(`${s.avg_steps} steps avg`);
  const tokens = s.tokens_in + s.tokens_out;
  if (tokens) parts.push(tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k tokens` : `${tokens} tokens`);
  if (s.last_active) parts.push(`last ${timeAgo(s.last_active, now)}`);
  return parts.join(' · ');
}
