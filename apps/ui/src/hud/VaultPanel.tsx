// Vault settings and status: the queue, watched folders, backups, local API keys and the command-bar shortcut.
import type { ApiKeyCreated, BackupStatus, HotkeyStatus } from '@universe/shared-types';
import { tokens } from '@universe/design-tokens';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { FolderPlus, Pause, Play, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { bridge } from '../lib/bridge';
import { formatAccelerator, formatBytes, timeAgo } from '../lib/format';
import { ITEM_TYPES } from '../lib/itemTypes';
import { useQueueStats, useVaultInfo } from '../lib/queries';
import { useUniverse } from '../state/store';
import { CopyButton, Dot, SectionTitle } from './ui';

function Section({ title, children, testid }: { title: string; children: ReactNode; testid?: string }) {
  return (
    <section className="space-y-2 border-b border-hairline-1 pb-4 last:border-0" data-testid={testid}>
      <SectionTitle>{title}</SectionTitle>
      {children}
    </section>
  );
}

function Button({
  onClick,
  children,
  disabled = false,
}: {
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-md border border-hairline-2 px-2.5 py-1 text-xs text-ink-2 transition-colors duration-150 hover:border-accent/60 hover:text-ink-1 disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function Overview() {
  const info = useVaultInfo(true);
  const data = info.data;
  if (!data) return <p className="text-xs text-ink-3">Loading…</p>;
  const types = Object.entries(data.by_type).sort((a, b) => b[1] - a[1]);
  return (
    <div className="space-y-2 text-xs">
      <p className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-ink-2" title={data.root}>
          {data.root}
        </span>
        <CopyButton text={data.root} label="Copy path" />
      </p>
      <p className="text-ink-2" data-testid="vault-counts">
        {data.items} items · {formatBytes(data.bytes)}
        {data.trashed ? ` · ${data.trashed} in the trash` : ''}
      </p>
      {types.length > 0 && (
        <p className="text-ink-3">
          {types
            .map(
              ([type, n]) =>
                `${n} ${ITEM_TYPES[type as keyof typeof ITEM_TYPES]?.plural.toLowerCase() ?? type}`,
            )
            .join(' · ')}
        </p>
      )}
      <p className={data.embedder ? 'text-ink-3' : 'text-amber'}>
        {data.embedder
          ? `Meaning search: ${data.embedder}`
          : 'Meaning search is off: install an embedding model (ollama pull nomic-embed-text). Keyword search works.'}
      </p>
    </div>
  );
}

function Queue() {
  const api = useApi();
  const stats = useQueueStats();
  const client = useQueryClient();
  const s = stats.data;
  if (!s) return <p className="text-xs text-ink-3">Loading…</p>;
  const busy = s.queued + s.leased;
  const toggle = () =>
    attempt(
      s.paused ? 'Resume' : 'Pause',
      (s.paused ? api.resumeQueue() : api.pauseQueue()).then(() =>
        client.invalidateQueries({ queryKey: ['queue'] }),
      ),
    );
  return (
    <div className="space-y-2 text-xs" data-testid="queue">
      <p className="flex items-center gap-2 text-ink-2">
        <Dot
          color={s.paused ? tokens.color.amber : busy ? tokens.color.cyan : tokens.color.green}
          pulse={busy > 0 && !s.paused}
        />
        {s.paused
          ? `Paused (${s.pause_reason ?? 'paused'}) · ${busy} waiting`
          : busy
            ? `Processing · ${busy} jobs left`
            : 'Idle · everything is processed'}
      </p>
      <p className="text-ink-3">
        {s.succeeded_last_hour} done in the last hour · {s.workers} worker{s.workers === 1 ? '' : 's'}
        {s.model_hold ? ' · model jobs wait while you chat' : ''}
        {s.dead ? ` · ${s.dead} failed for good` : ''}
      </p>
      <Button onClick={toggle}>
        {s.paused ? <Play className="size-3.5" aria-hidden /> : <Pause className="size-3.5" aria-hidden />}
        {s.paused ? 'Resume background work' : 'Pause background work'}
      </Button>
    </div>
  );
}

function WatchedFolders() {
  const api = useApi();
  const client = useQueryClient();
  const folders = useQuery({ queryKey: ['watched'], queryFn: api.watchedFolders });
  const projectId = useUniverse((s) => s.selectedProjectId);
  const reload = () => client.invalidateQueries({ queryKey: ['watched'] });
  const add = () =>
    attempt(
      'Add a watched folder',
      bridge()
        .pickFolder('Watch a folder (new files are copied into the vault)')
        .then((path) =>
          path
            ? api.addWatchedFolder({ path, recursive: true, default_project_id: projectId }).then(reload)
            : undefined,
        ),
    );
  return (
    <div className="space-y-2" data-testid="watched-folders">
      {folders.data?.length === 0 && (
        <p className="text-xs text-ink-3">
          None yet. New and changed files in a watched folder are copied into the vault.
        </p>
      )}
      <ul className="space-y-1.5">
        {folders.data?.map((f) => (
          <li key={f.id} className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={f.enabled}
              aria-label={`Watch ${f.path}`}
              onChange={(e) =>
                attempt('Update folder', api.setWatchedFolderEnabled(f.id, e.target.checked).then(reload))
              }
            />
            <span
              className={`flex-1 truncate font-mono ${f.exists ? 'text-ink-2' : 'text-danger'}`}
              title={f.path}
            >
              {f.path}
            </span>
            <button
              type="button"
              title="Scan now"
              onClick={() => attempt('Scan', api.scanWatchedFolder(f.id))}
            >
              <RefreshCw className="size-3.5 text-ink-3 hover:text-ink-1" aria-label="Scan now" />
            </button>
            <button
              type="button"
              title="Stop watching"
              onClick={() => attempt('Remove folder', api.removeWatchedFolder(f.id).then(reload))}
            >
              <Trash2 className="size-3.5 text-ink-3 hover:text-danger" aria-label="Stop watching" />
            </button>
          </li>
        ))}
      </ul>
      <Button onClick={add}>
        <FolderPlus className="size-3.5" aria-hidden /> Watch a folder…
      </Button>
    </div>
  );
}

function randomPassword(): string {
  const words = new Uint8Array(18);
  crypto.getRandomValues(words);
  return Array.from(words, (b) => 'abcdefghjkmnpqrstuvwxyz23456789'[b % 31])
    .join('')
    .replace(/(.{6})(?=.)/g, '$1-');
}

function BackupSetup({ onDone }: { onDone: () => void }) {
  const api = useApi();
  const [target, setTarget] = useState('');
  const [password] = useState(randomPassword);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-2 text-xs">
      <p className="leading-relaxed text-ink-3">
        Encrypted, versioned backups with restic, daily. Choose an external drive or NAS folder.
      </p>
      <div className="flex gap-2">
        <input
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="D:\\UniverseBackup"
          aria-label="Backup folder"
          className="min-w-0 flex-1 rounded-md border border-hairline-2 bg-space-2 px-2 py-1 font-mono text-ink-1"
        />
        <Button
          onClick={() =>
            attempt(
              'Choose folder',
              bridge()
                .pickFolder('Backup folder')
                .then((p) => p && setTarget(p)),
            )
          }
        >
          Choose…
        </Button>
      </div>
      <div className="rounded-md border border-amber/40 p-2">
        <p className="text-ink-2">
          Backup password. Keep it somewhere safe: without it a backup can't be restored on a new PC.
        </p>
        <p
          className="mt-1 flex items-center justify-between gap-2 font-mono text-ink-1"
          data-testid="backup-password"
        >
          {password}
          <CopyButton text={password} />
        </p>
        <label className="mt-1 flex items-center gap-2 text-ink-2">
          <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> I saved this
          password
        </label>
      </div>
      {error && <p className="text-danger">{error}</p>}
      <Button
        disabled={!target || !saved || busy}
        onClick={() => {
          setBusy(true);
          setError(null);
          api
            .configureBackups({ target, password, enabled: true, schedule_hour: 3 })
            .then(onDone, (err: Error) => setError(err.message))
            .finally(() => setBusy(false));
        }}
      >
        <ShieldCheck className="size-3.5" aria-hidden /> {busy ? 'Setting up…' : 'Set up backups'}
      </Button>
    </div>
  );
}

function Backups() {
  const api = useApi();
  const client = useQueryClient();
  const status = useQuery({ queryKey: ['backups'], queryFn: api.backupStatus, refetchInterval: 5_000 });
  const snapshots = useQuery({
    queryKey: ['snapshots', status.data?.last_success?.id],
    queryFn: api.snapshots,
    enabled: !!status.data?.configured,
  });
  const reload = () => client.invalidateQueries({ queryKey: ['backups'] });
  const s: BackupStatus | undefined = status.data;
  if (!s) return <p className="text-xs text-ink-3">Loading…</p>;
  if (!s.restic_found)
    return (
      <p className="flex items-center justify-between gap-2 text-xs text-amber">
        restic isn't installed. <CopyButton text={s.install_hint} label="Copy install command" />
      </p>
    );
  if (!s.configured) return <BackupSetup onDone={reload} />;
  const last = s.last;
  return (
    <div className="space-y-2 text-xs" data-testid="backups">
      <p className="truncate font-mono text-ink-2" title={s.target ?? ''}>
        {s.target}
      </p>
      <p className={last?.status === 'failed' ? 'text-danger' : 'text-ink-3'}>
        {s.running
          ? 'Backing up…'
          : last
            ? last.status === 'failed'
              ? `Last backup failed: ${last.error}`
              : `Last backup ${timeAgo(last.started_at)}${last.verified_at ? ' · restore tested' : ''}`
            : 'No backup yet'}
        {s.enabled ? ` · daily at ${String(s.schedule_hour).padStart(2, '0')}:00` : ' · schedule off'}
      </p>
      {!s.password_stored && (
        <p className="text-amber">The password isn't in the credential store: set backups up again.</p>
      )}
      <div className="flex flex-wrap gap-1.5">
        <Button disabled={s.running} onClick={() => attempt('Back up now', api.runBackup().then(reload))}>
          Back up now
        </Button>
        <Button
          disabled={s.running || !s.last_success}
          onClick={() => attempt('Test restore', api.verifyBackup().then(reload))}
        >
          Test a restore
        </Button>
      </div>
      {snapshots.data && snapshots.data.length > 0 && (
        <details>
          <summary className="cursor-pointer text-ink-3">{snapshots.data.length} snapshots</summary>
          <ul className="mt-1 space-y-1">
            {snapshots.data.slice(0, 10).map((snap) => (
              <li key={snap.id} className="flex items-center justify-between gap-2">
                <span className="font-mono text-ink-2">
                  {snap.short_id} · {new Date(snap.time).toLocaleString()}
                </span>
                <button
                  type="button"
                  className="text-ink-3 hover:text-ink-1"
                  onClick={() =>
                    attempt(
                      'Restore',
                      bridge()
                        .pickFolder('Restore into an empty folder (the vault is never overwritten)')
                        .then((target) => (target ? api.restoreBackup(snap.short_id, target) : null)),
                    )
                  }
                >
                  Restore…
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ApiKeys() {
  const api = useApi();
  const client = useQueryClient();
  const keys = useQuery({ queryKey: ['api-keys'], queryFn: api.apiKeys });
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const reload = () => client.invalidateQueries({ queryKey: ['api-keys'] });
  return (
    <div className="space-y-2 text-xs">
      <p className="leading-relaxed text-ink-3">
        Let your own scripts add to the vault (<span className="font-mono">POST /api/v1/capture</span>) or
        search it (<span className="font-mono">GET /api/v1/search</span>) on this PC.
      </p>
      {created && (
        <div className="rounded-md border border-amber/40 p-2">
          <p className="text-ink-2">Copy this key now; it won't be shown again.</p>
          <p className="mt-1 flex items-center justify-between gap-2 font-mono break-all text-ink-1">
            {created.key} <CopyButton text={created.key} />
          </p>
        </div>
      )}
      <ul className="space-y-1">
        {keys.data
          ?.filter((k) => !k.revoked_at)
          .map((k) => (
            <li key={k.id} className="flex items-center gap-2">
              <span className="flex-1 truncate text-ink-2">
                {k.name}{' '}
                <span className="font-mono text-ink-3">
                  {k.prefix}… · {k.scopes.join(', ')}
                </span>
              </span>
              <button
                type="button"
                title="Revoke"
                onClick={() => attempt('Revoke key', api.revokeApiKey(k.id).then(reload))}
              >
                <Trash2 className="size-3.5 text-ink-3 hover:text-danger" aria-label="Revoke" />
              </button>
            </li>
          ))}
      </ul>
      <Button
        onClick={() => {
          const name = window.prompt('Name for this key (e.g. "phone shortcut")');
          if (name)
            attempt(
              'Create key',
              api.createApiKey(name, ['capture', 'search']).then((k) => {
                setCreated(k);
                void reload();
              }),
            );
        }}
      >
        New API key…
      </Button>
    </div>
  );
}

function Hotkey() {
  const [status, setStatus] = useState<HotkeyStatus | null>(null);
  const [draft, setDraft] = useState('');
  useEffect(() => {
    void bridge()
      .getHotkey()
      .then((s) => {
        setStatus(s);
        setDraft(s.accelerator);
      });
  }, []);
  if (!status) return null;
  return (
    <div className="space-y-2 text-xs">
      <p className={status.registered ? 'text-ink-3' : 'text-amber'}>
        {status.registered
          ? `Press ${formatAccelerator(status.accelerator)} in any app to search or capture.`
          : (status.error ?? 'Not registered')}
      </p>
      <div className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="Command bar shortcut"
          className="min-w-0 flex-1 rounded-md border border-hairline-2 bg-space-2 px-2 py-1 font-mono text-ink-1"
        />
        <Button onClick={() => attempt('Change shortcut', bridge().setHotkey(draft).then(setStatus))}>
          Save
        </Button>
      </div>
      <p className="text-ink-3">
        Ctrl+Space can clash with Chinese/Japanese/Korean input methods; Alt+Space or Ctrl+Shift+Space are
        good alternatives.
      </p>
    </div>
  );
}

export function VaultPanel() {
  return (
    <div className="space-y-4" data-testid="vault-panel">
      <Section title="Vault">
        <Overview />
      </Section>
      <Section title="Background work">
        <Queue />
      </Section>
      <Section title="Watched folders">
        <WatchedFolders />
      </Section>
      <Section title="Backups">
        <Backups />
      </Section>
      <Section title="Command bar">
        <Hotkey />
      </Section>
      <Section title="Local API">
        <ApiKeys />
      </Section>
    </div>
  );
}
