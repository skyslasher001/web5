// Research (SPEC §13, ADR-0015): ask the live web and follow the task in Agents, watch topics or pages for
// changes, and see what was sent where. Web content is untrusted: the researcher cites it, never obeys it, and
// saving a report to the vault asks you first (an approval in the Approvals tray).
import type { Watchlist } from '@universe/shared-types';
import { tokens } from '@universe/design-tokens';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Globe, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { timeAgo } from '../lib/format';
import { useEngine, useSentRequests, useWatchlists } from '../lib/queries';
import { useUniverse } from '../state/store';
import { Button, Dot, inputClass, Section } from './ui';

function Ask({ blocked, reason }: { blocked: boolean; reason: string }) {
  const api = useApi();
  const [q, setQ] = useState('');
  const [mode, setMode] = useState<'quick' | 'deep'>('quick');
  const ask = () => {
    const text = q.trim();
    if (text.length < 2 || blocked) return;
    attempt(
      'Research',
      api.research(text, mode).then((r) => {
        useUniverse.getState().addNotice('info', 'Researcher is on it: follow it in Agents → Tasks');
        useUniverse.getState().selectTask(r.task_id);
        setQ('');
      }),
    );
  };
  return (
    <Section title="Ask the web">
      <textarea
        value={q}
        onChange={(e) => setQ(e.target.value)}
        rows={2}
        placeholder="What were the big local-first software releases this year?"
        aria-label="Research question"
        className={`${inputClass} w-full resize-none`}
        data-testid="research-ask"
      />
      <div className="flex items-center justify-between gap-2">
        <div role="radiogroup" aria-label="Depth" className="flex gap-1 text-xs">
          {(['quick', 'deep'] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-md px-2 py-1 ${mode === m ? 'bg-space-3 text-ink-1' : 'text-ink-3 hover:text-ink-2'}`}
              data-testid={`research-mode-${m}`}
            >
              {m === 'quick' ? 'Quick' : 'Deep (saves a report)'}
            </button>
          ))}
        </div>
        <Button onClick={ask} disabled={blocked || q.trim().length < 2} testid="research-send">
          <Search className="size-3.5" aria-hidden /> Research
        </Button>
      </div>
      {blocked && <p className="text-[11px] text-amber">{reason}</p>}
      <p className="text-[11px] leading-relaxed text-ink-3">
        The researcher plans its searches, cites every source, and reports conflicts. Pages from the web are
        untrusted — it quotes them, never follows them, and a deep report asks you before it saves.
      </p>
    </Section>
  );
}

function Hits({ id }: { id: string }) {
  const api = useApi();
  const hits = useQuery({ queryKey: ['research', 'hits', id], queryFn: () => api.watchlistHits(id) });
  if (!hits.data) return <p className="pl-5 text-[11px] text-ink-3">Loading changes…</p>;
  if (hits.data.length === 0) return <p className="pl-5 text-[11px] text-ink-3">No changes recorded yet.</p>;
  return (
    <ul className="space-y-1 pl-5" data-testid="watchlist-hits">
      {hits.data.map((h) => (
        <li key={h.id} className="text-[11px]">
          <span className="text-ink-2">{h.summary}</span>{' '}
          <span className="text-ink-3">· {timeAgo(h.found_at)}</span>
        </li>
      ))}
    </ul>
  );
}

function WatchRow({ w, refresh }: { w: Watchlist; refresh: () => void }) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const check = () => {
    setBusy(true);
    attempt(
      'Check',
      api
        .checkWatchlist(w.id)
        .then(refresh)
        .finally(() => setBusy(false)),
    );
  };
  return (
    <li className="rounded-md border border-hairline-1 p-2 text-xs" data-testid="watchlist">
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => setOpen(!open)} className="text-ink-3" aria-label="Show changes">
          {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
        <Dot color={w.enabled ? tokens.color.green : tokens.color.slate} />
        <span className="flex-1 truncate text-ink-1">{w.label || w.target}</span>
        {w.unseen > 0 && (
          <span
            className="rounded-full bg-accent/20 px-1.5 text-[10px] text-accent"
            data-testid="watchlist-unseen"
          >
            {w.unseen} new
          </span>
        )}
        <span className="text-[10px] text-ink-3">{w.kind}</span>
      </div>
      <div className="mt-1 flex items-center gap-2 pl-6">
        {w.last_summary && <span className="flex-1 truncate text-[11px] text-ink-3">{w.last_summary}</span>}
        <button
          type="button"
          onClick={check}
          disabled={busy}
          className="text-ink-3 hover:text-accent"
          title="Check now"
        >
          <RefreshCw className={`size-3 ${busy ? 'orb-spin' : ''}`} aria-label="Check now" />
        </button>
        <button
          type="button"
          onClick={() => attempt('Toggle', api.setWatchlistEnabled(w.id, !w.enabled).then(refresh))}
          className="text-[11px] text-ink-3 hover:text-ink-1"
        >
          {w.enabled ? 'Pause' : 'Resume'}
        </button>
        <button
          type="button"
          onClick={() => attempt('Remove', api.deleteWatchlist(w.id).then(refresh))}
          className="text-ink-3 hover:text-danger"
          title="Remove"
        >
          <Trash2 className="size-3" aria-label="Remove" />
        </button>
      </div>
      {open && <div className="mt-1.5">{<Hits id={w.id} />}</div>}
    </li>
  );
}

function Watchlists() {
  const api = useApi();
  const client = useQueryClient();
  const watchlists = useWatchlists();
  const refresh = () => client.invalidateQueries({ queryKey: ['research', 'watchlists'] });
  const [kind, setKind] = useState<'topic' | 'page'>('topic');
  const [target, setTarget] = useState('');
  const add = () => {
    const value = target.trim();
    if (value.length < 2) return;
    attempt(
      'Watch',
      api.createWatchlist({ kind, target: value }).then(() => {
        setTarget('');
        return refresh();
      }),
    );
  };
  return (
    <Section title="Watchlists" testid="watchlists">
      <div className="flex gap-1">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as 'topic' | 'page')}
          className="rounded-md border border-hairline-2 bg-space-2 px-2 py-1 text-xs text-ink-1"
          aria-label="Watch kind"
        >
          <option value="topic">Topic</option>
          <option value="page">Page</option>
        </select>
        <input
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder={kind === 'topic' ? 'a search to watch' : 'https://a-page-to-watch'}
          aria-label="What to watch"
          className={`${inputClass} flex-1`}
          data-testid="watchlist-target"
        />
        <Button onClick={add} disabled={target.trim().length < 2} testid="watchlist-add">
          <Plus className="size-3.5" aria-hidden />
        </Button>
      </div>
      {watchlists.data?.length === 0 && <p className="text-xs text-ink-3">Nothing watched yet.</p>}
      <ul className="space-y-2">
        {watchlists.data?.map((w) => (
          <WatchRow key={w.id} w={w} refresh={refresh} />
        ))}
      </ul>
    </Section>
  );
}

function SentWhere() {
  const requests = useSentRequests(true);
  return (
    <Section title="Sent where" testid="sent-where">
      {requests.data?.length === 0 && (
        <p className="text-xs text-ink-3">Nothing has left this machine yet.</p>
      )}
      <ul className="space-y-0.5 font-mono text-[11px]">
        {requests.data?.slice(0, 20).map((r, k) => (
          <li key={k} className="flex items-baseline justify-between gap-2">
            <span className="truncate text-ink-2">
              {r.scheme}://{r.host}
            </span>
            <span className="shrink-0 text-ink-3">
              {r.purpose} · {timeAgo(r.ts)}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function ResearchPanel() {
  const online = useUniverse((s) => s.connection === 'online');
  const engine = useEngine();
  const killed = !!engine.data?.killswitch_engaged;
  const blocked = !online || killed;
  const reason = killed
    ? 'The kill switch is on: agents are stopped.'
    : !online
      ? 'Core is offline: reconnect to research.'
      : '';
  return (
    <div className="space-y-4" data-testid="research-panel">
      <div className="flex items-center gap-2 text-sm text-ink-2">
        <Globe className="size-4 text-accent" aria-hidden /> Researcher
      </div>
      <Ask blocked={blocked} reason={reason} />
      <Watchlists />
      <SentWhere />
    </div>
  );
}
