// The command bar window (SPEC §6, ARCHITECTURE.md §6.4): search as you type, Enter to open or follow an
// intent ("open …", "go to …", "show …"), Tab for quick capture. REST only: no WebSocket, no 3D.
import type { BridgeConfig, SearchResponse } from '@universe/shared-types';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import {
  ClipboardPaste,
  CornerDownLeft,
  LoaderCircle,
  NotebookPen,
  Orbit,
  Search,
  Sparkles,
} from 'lucide-react';
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { CoreApi, ApiError } from '../lib/api';
import { ApiContext, useApi } from '../lib/api-context';
import { bridge } from '../lib/bridge';
import { installErrorReporting } from '../lib/errorReporting';
import { formatDate, ITEM_TYPES, splitMarks } from '../lib/itemTypes';
import { useDebounced } from '../lib/queries';
import { Kbd } from '../hud/ui';
import { TypeGlyph } from '../views2d/ItemVisual';
import {
  actionForRecall,
  actionForRow,
  parseCapture,
  rowForEnter,
  rowsFor,
  type BarAction,
  type Row,
} from './logic';

type Mode = 'search' | 'capture';
type Status = { tone: 'info' | 'good' | 'bad'; text: string } | null;

const message = (err: unknown) =>
  err instanceof ApiError || err instanceof Error ? err.message : String(err);

function Marked({ text }: { text: string }) {
  return (
    <>
      {splitMarks(text).map((part, i) =>
        part.mark ? (
          <mark key={i} className="rounded-sm bg-accent/20 px-0.5 text-ink-1">
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

function ResultRow({ row, active, onPick }: { row: Row; active: boolean; onPick: () => void }) {
  const base = `flex w-full items-center gap-3 rounded-md px-3 py-2 text-left ${active ? 'bg-space-3 text-ink-1' : 'text-ink-2'}`;
  if (row.kind === 'capture') {
    return (
      <button
        type="button"
        className={base}
        onClick={onPick}
        data-testid="bar-capture-row"
        aria-selected={active}
      >
        <NotebookPen className="size-[18px] text-accent-2" aria-hidden />
        <span className="flex-1 truncate text-sm">
          Save “{row.text}” as a note <span className="text-xs text-ink-3">to the inbox</span>
        </span>
        <Kbd>Ctrl S</Kbd>
      </button>
    );
  }
  const { item, snippet } = row.hit;
  return (
    <button type="button" className={base} onClick={onPick} data-testid="bar-hit" aria-selected={active}>
      <TypeGlyph item={item} />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-sm">{item.title}</span>
        {snippet && (
          <span className="truncate text-xs text-ink-3">
            <Marked text={snippet} />
          </span>
        )}
      </span>
      <span className="shrink-0 text-[11px] text-ink-3">
        {ITEM_TYPES[item.type].label} · {formatDate(item.captured_at)}
      </span>
    </button>
  );
}

function CommandBar() {
  const api = useApi();
  const [mode, setMode] = useState<Mode>('search');
  const [query, setQuery] = useState('');
  const [note, setNote] = useState('');
  const [kind, setKind] = useState<'note' | 'idea'>('note');
  // The highlighted row, for the query it was chosen in: a new query starts back at the top.
  const [cursor, setCursor] = useState({ q: '', index: 0, picked: false });
  const [status, setStatus] = useState<Status>(null);
  const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState(0); // bumps on every show so the bar animates in each time
  const searchInput = useRef<HTMLInputElement>(null);
  const noteInput = useRef<HTMLTextAreaElement>(null);

  const q = useDebounced(query.trim(), 70);
  const results = useQuery<SearchResponse>({
    queryKey: ['bar-search', q],
    queryFn: () => api.search({ q, limit: 8 }),
    enabled: mode === 'search' && q.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 2_000,
  });
  const hits = q && query.trim() ? (results.data?.hits ?? []) : [];
  const rows = rowsFor(query, hits);
  const active = cursor.q === q ? Math.min(cursor.index, Math.max(0, rows.length - 1)) : 0;
  const picked = cursor.q === q && cursor.picked; // the user moved the highlight with the arrows
  // The hits answer what's typed now (not the previous query's, kept on screen while the new one loads).
  const fresh = q === query.trim() && results.isSuccess && !results.isPlaceholderData;

  useEffect(() => {
    const focus = (next: Mode) => {
      setShown((n) => n + 1);
      setMode(next);
      setStatus(null);
      setBusy(false);
      requestAnimationFrame(() => {
        const el = next === 'search' ? searchInput.current : noteInput.current;
        el?.focus();
        el?.select();
      });
    };
    focus('search');
    return bridge().onCommandBarShow(focus);
  }, []);

  const hide = () => bridge().hideCommandBar();

  const save = async (raw: string, itemKind: 'note' | 'idea' = 'note') => {
    const draft = parseCapture(raw);
    if (!draft.text) return;
    setBusy(true);
    try {
      // A note unless it's an idea: Core makes a lone URL a link.
      await api.capture({
        text: draft.text,
        tags: draft.tags,
        source: 'quick_capture',
        ...(itemKind === 'idea' ? { kind: 'idea' } : {}),
      });
      setStatus({ tone: 'good', text: 'Saved to your inbox' });
      setQuery('');
      setNote('');
      setTimeout(hide, 450);
    } catch (err) {
      setStatus({ tone: 'bad', text: `Not saved: ${message(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const run = async (action: BarAction) => {
    if (action.kind === 'none') {
      setStatus({ tone: 'info', text: action.message });
    } else if (action.kind === 'capture') {
      await save(action.text);
    } else if (action.kind === 'focus') {
      bridge().focus(action.target); // main hides the bar and brings UNIVERSE forward
    } else {
      setBusy(true);
      try {
        const opened = await api.openItem(action.itemId);
        const error = await bridge().openPath(opened.abs_path);
        if (error) throw new Error(error);
        hide();
      } catch (err) {
        setStatus({ tone: 'bad', text: `Couldn't open it: ${message(err)}` });
      } finally {
        setBusy(false);
      }
    }
  };

  const enter = async (reveal: boolean) => {
    const text = query.trim();
    if (!text) return;
    const row = rowForEnter(rows, active, picked, reveal, fresh);
    if (row) return run(actionForRow(row, reveal));
    setBusy(true);
    try {
      const result = await api.recall(text);
      setBusy(false);
      await run(actionForRecall(result, text));
    } catch (err) {
      setBusy(false);
      setStatus({ tone: 'bad', text: message(err) });
    }
  };

  const onSearchKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (rows.length === 0) return;
      const index = e.key === 'ArrowDown' ? Math.min(rows.length - 1, active + 1) : Math.max(0, active - 1);
      setCursor({ q, index, picked: true });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      void enter(e.ctrlKey || e.metaKey);
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      void save(query);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      hide();
    } else if (e.key === 'Tab') {
      e.preventDefault();
      const next = mode === 'search' ? 'capture' : 'search';
      if (next === 'capture' && query.trim() && !note) setNote(query.trim());
      setMode(next);
      setStatus(null);
      requestAnimationFrame(() => (next === 'search' ? searchInput.current : noteInput.current)?.focus());
    }
  };

  const clipboard = async () => {
    setBusy(true);
    try {
      const result = await bridge().captureClipboard();
      setStatus({ tone: result.ok ? 'good' : 'bad', text: result.message });
      if (result.ok) setTimeout(hide, 600);
    } finally {
      setBusy(false);
    }
  };

  const hint = (keys: string, label: string): ReactNode => (
    <span className="flex items-center gap-1.5">
      <Kbd>{keys}</Kbd>
      {label}
    </span>
  );

  return (
    <div
      key={shown}
      className="hud-enter flex h-full flex-col overflow-hidden rounded-xl border border-hairline-2 bg-space-1 text-ink-1"
      onKeyDown={onKeyDown}
      data-testid="command-bar"
    >
      <div className="flex items-center gap-3 border-b border-hairline-1 px-4">
        {mode === 'search' ? (
          <Search className="size-5 text-ink-3" aria-hidden />
        ) : (
          <NotebookPen className="size-5 text-accent-2" aria-hidden />
        )}
        {mode === 'search' ? (
          <input
            ref={searchInput}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setStatus(null);
            }}
            onKeyDown={onSearchKey}
            placeholder="Search, or try “open budget”, “go to music”…"
            aria-label="Search your vault"
            data-testid="bar-input"
            spellCheck={false}
            className="h-14 flex-1 bg-transparent text-base placeholder:text-ink-3 focus:outline-none"
          />
        ) : (
          <p className="h-14 flex-1 content-center text-sm text-ink-2">Quick capture</p>
        )}
        {busy && <LoaderCircle className="size-4 orb-spin text-ink-3" aria-label="Working" />}
        <div
          className="flex rounded-full border border-hairline-2 p-0.5 text-xs"
          role="tablist"
          aria-label="Mode"
        >
          {(['search', 'capture'] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-full px-2.5 py-0.5 capitalize ${mode === m ? 'bg-space-3 text-ink-1' : 'text-ink-3'}`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {mode === 'search' ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-2" role="listbox" aria-label="Results">
          {rows.map((row, i) => (
            <ResultRow
              key={row.kind === 'hit' ? row.hit.item.id : 'capture'}
              row={row}
              active={i === active}
              onPick={() => void run(actionForRow(row, false))}
            />
          ))}
          {!query.trim() && (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-ink-3">
              <Orbit className="size-6 text-accent" aria-hidden />
              <p>Find anything in your vault by name, words inside it, or meaning.</p>
              <p className="text-xs">Tab switches to quick capture.</p>
            </div>
          )}
          {query.trim() && results.data && hits.length === 0 && !results.isFetching && (
            <p className="px-3 py-2 text-xs text-ink-3">No matches yet.</p>
          )}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-2 p-4">
          <textarea
            ref={noteInput}
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
              setStatus(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                void save(note, kind);
              }
            }}
            placeholder="Write a note or paste a link. #tags become tags."
            aria-label="Note"
            data-testid="bar-note"
            className="min-h-0 flex-1 resize-none rounded-lg border border-hairline-1 bg-space-2 p-3 text-sm leading-relaxed placeholder:text-ink-3 focus:border-accent/50 focus:outline-none"
          />
          <div className="flex items-center gap-2">
            {(['note', 'idea'] as const).map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={kind === k}
                onClick={() => setKind(k)}
                className={`flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs capitalize ${
                  kind === k ? 'border-accent/60 bg-accent/10 text-ink-1' : 'border-hairline-2 text-ink-3'
                }`}
              >
                {k === 'idea' && <Sparkles className="size-3" aria-hidden />}
                {k}
              </button>
            ))}
            <span className="flex-1" />
            <button
              type="button"
              onClick={() => void clipboard()}
              className="flex items-center gap-1.5 rounded-md border border-hairline-2 px-2.5 py-1 text-xs text-ink-2 hover:border-accent/60"
            >
              <ClipboardPaste className="size-3.5" aria-hidden /> Save clipboard
            </button>
            <button
              type="button"
              disabled={!note.trim() || busy}
              onClick={() => void save(note, kind)}
              data-testid="bar-save"
              className="flex items-center gap-1.5 rounded-md bg-accent/20 px-3 py-1 text-xs text-ink-1 hover:bg-accent/30 disabled:opacity-40"
            >
              <CornerDownLeft className="size-3.5" aria-hidden /> Save
            </button>
          </div>
        </div>
      )}

      <footer className="flex items-center gap-4 border-t border-hairline-1 px-4 py-2 text-[11px] text-ink-3">
        {status ? (
          <span
            role="status"
            data-testid="bar-status"
            className={
              status.tone === 'bad' ? 'text-danger' : status.tone === 'good' ? 'text-green' : 'text-ink-2'
            }
          >
            {status.text}
          </span>
        ) : mode === 'search' ? (
          <>
            {hint('Enter', 'open')}
            {hint('Ctrl Enter', 'show in UNIVERSE')}
            {hint('Tab', 'capture')}
          </>
        ) : (
          <>
            {hint('Ctrl Enter', 'save')}
            {hint('Tab', 'search')}
          </>
        )}
        <span className="flex-1" />
        {!status && mode === 'search' && results.data && q && (
          <span className="font-mono" title="Search time in Core">
            {Math.round(results.data.took_ms)} ms
          </span>
        )}
        {hint('Esc', 'close')}
      </footer>
    </div>
  );
}

/** The command bar's own root: a REST client from the bridge config, nothing else. */
export function CommandBarRoot() {
  const [api, setApi] = useState<CoreApi | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const offErrors = installErrorReporting();
    bridge()
      .getConfig()
      .then((config: BridgeConfig) => setApi(new CoreApi(config.coreUrl, config.token)))
      .catch((err: unknown) => setError(message(err)));
    return offErrors;
  }, []);
  if (!api) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-hairline-2 bg-space-1 text-sm text-ink-3">
        {error ?? 'Starting…'}
      </div>
    );
  }
  return (
    <ApiContext.Provider value={api}>
      <CommandBar />
    </ApiContext.Provider>
  );
}
