// 2D views of the vault (SPEC §7: "real work never requires 3D"): Grid and List over the same query,
// virtualized so 50k items scroll smoothly.
import type { ItemSummary, SearchHit } from '@universe/shared-types';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Grid2x2, List, LoaderCircle, Search, Sparkles, Trash2, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useApi } from '../lib/api-context';
import { formatBytes } from '../lib/format';
import { formatDate, ITEM_TYPES, sameTypes, splitMarks, TYPE_CHIPS } from '../lib/itemTypes';
import { useItemsView, useProjects } from '../lib/queries';
import { openItem, trashItem } from '../lib/vaultActions';
import { useUniverse, type View } from '../state/store';
import { ItemVisual, PipelineDot, TypeGlyph } from './ItemVisual';

const CARD_W = 172;
const CARD_H = 212;
const ROW_H = 46;
/** The last focus request from the search field that was handled (survives remounts). */
let handledResultsTick = 0;

function Snippet({ text }: { text: string }) {
  return (
    <span className="line-clamp-1 text-xs text-ink-3">
      {splitMarks(text).map((part, i) =>
        part.mark ? (
          <mark key={i} className="rounded-sm bg-accent/20 px-0.5 text-ink-1">
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </span>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors duration-150 ${
        active ? 'border-accent/60 bg-accent/10 text-ink-1' : 'border-hairline-2 text-ink-3 hover:text-ink-2'
      }`}
    >
      {children}
    </button>
  );
}

function Toolbar({ count, searching, semantic }: { count: number; searching: boolean; semantic: ReactNode }) {
  const s = useUniverse();
  const projects = useProjects();
  const project = projects.data?.find((p) => p.id === s.selectedProjectId);
  const viewButton = (view: View, label: string, Icon: typeof List) => (
    <button
      type="button"
      title={`${label} view`}
      aria-pressed={s.view === view}
      onClick={() => s.setView(view)}
      className={`rounded-md p-1.5 ${s.view === view ? 'bg-space-3 text-ink-1' : 'text-ink-3 hover:text-ink-2'}`}
    >
      <Icon className="size-4" aria-label={`${label} view`} />
    </button>
  );
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-hairline-1 px-4 py-2.5">
      <div className="flex gap-1">
        <Chip active={s.typeFilter.length === 0} onClick={() => s.setTypeFilter([])}>
          All
        </Chip>
        {TYPE_CHIPS.map((chip) => (
          <Chip
            key={chip.label}
            active={sameTypes(s.typeFilter, chip.types)}
            onClick={() => s.setTypeFilter(sameTypes(s.typeFilter, chip.types) ? [] : chip.types)}
          >
            {chip.label}
          </Chip>
        ))}
      </div>
      {project && (
        <span className="flex items-center gap-1 rounded-full border border-hairline-2 px-2.5 py-0.5 text-xs text-ink-2">
          {project.name}
          <button type="button" aria-label="Show every galaxy" onClick={() => s.selectProject(null)}>
            <X className="size-3" aria-hidden />
          </button>
        </span>
      )}
      <span className="flex-1" />
      {semantic}
      <span className="font-mono text-xs text-ink-3" data-testid="items-count">
        {count} {searching ? 'found' : count === 1 ? 'item' : 'items'}
      </span>
      {!searching && (
        <select
          aria-label="Sort"
          value={s.sort}
          onChange={(e) => s.setSort(e.target.value as typeof s.sort)}
          className="rounded-md border border-hairline-2 bg-space-2 px-2 py-1 text-xs text-ink-2"
        >
          <option value="added">Recently added</option>
          <option value="captured">Date taken</option>
          <option value="opened">Recently opened</option>
          <option value="title">Title</option>
        </select>
      )}
      <button
        type="button"
        title="Trash"
        aria-pressed={s.showTrash}
        onClick={() => s.setShowTrash(!s.showTrash)}
        className={`rounded-md p-1.5 ${s.showTrash ? 'bg-danger/15 text-danger' : 'text-ink-3 hover:text-ink-2'}`}
      >
        <Trash2 className="size-4" aria-label="Trash" />
      </button>
      {viewButton('grid', 'Grid', Grid2x2)}
      {viewButton('list', 'List', List)}
    </div>
  );
}

function useColumns(ref: React.RefObject<HTMLDivElement | null>): number {
  const [columns, setColumns] = useState(4);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() =>
      setColumns(Math.max(1, Math.floor((el.clientWidth - 16) / CARD_W))),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return columns;
}

function useNearEnd(lastIndex: number | undefined, count: number, onNearEnd: () => void): void {
  useEffect(() => {
    if (lastIndex !== undefined && lastIndex >= count - 5) onNearEnd();
  }, [lastIndex, count, onNearEnd]);
}

interface ViewProps {
  items: ItemSummary[];
  onOpen: (item: ItemSummary) => void;
  onNearEnd: () => void;
}

function GridView({ items, onOpen, onNearEnd }: ViewProps) {
  const parent = useRef<HTMLDivElement>(null);
  const columns = useColumns(parent);
  const selected = useUniverse((s) => s.selectedItemId);
  const select = useUniverse((s) => s.selectItem);
  const rows = Math.ceil(items.length / columns);
  // eslint-disable-next-line react-hooks/incompatible-library -- expected: the virtualizer re-renders on scroll by design
  const virtualizer = useVirtualizer({
    count: rows,
    getScrollElement: () => parent.current,
    estimateSize: () => CARD_H,
    overscan: 4,
  });
  useNearEnd(virtualizer.getVirtualItems().at(-1)?.index, rows, onNearEnd);
  return (
    <div ref={parent} className="h-full overflow-y-auto px-2 py-2" data-testid="items-grid">
      <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
        {virtualizer.getVirtualItems().map((row) => (
          <div
            key={row.key}
            className="absolute inset-x-0 flex gap-2 px-2"
            style={{ top: row.start, height: CARD_H }}
          >
            {items.slice(row.index * columns, row.index * columns + columns).map((item) => (
              <button
                key={item.id}
                type="button"
                data-testid="item-card"
                aria-selected={selected === item.id}
                onClick={() => select(item.id)}
                onDoubleClick={() => onOpen(item)}
                className={`flex w-[164px] shrink-0 flex-col overflow-hidden rounded-lg border text-left transition-[border-color,background-color,transform] duration-150 hover:-translate-y-0.5 motion-reduce:transform-none ${
                  selected === item.id
                    ? 'border-accent/70 bg-space-3/70'
                    : 'border-hairline-1 hover:border-hairline-2'
                }`}
              >
                <ItemVisual item={item} className="h-[132px] w-full bg-space-1" />
                <span className="flex flex-1 flex-col gap-1 p-2">
                  <span className="line-clamp-2 text-xs leading-snug text-ink-1">{item.title}</span>
                  <span className="mt-auto flex items-center gap-1.5 text-[11px] text-ink-3">
                    <TypeGlyph item={item} size={12} />
                    {formatDate(item.captured_at)}
                    <span className="flex-1" />
                    <PipelineDot status={item.pipeline_status} />
                  </span>
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function ListView({ items, hits, onOpen, onNearEnd }: ViewProps & { hits: Map<string, SearchHit> }) {
  const parent = useRef<HTMLDivElement>(null);
  const selected = useUniverse((s) => s.selectedItemId);
  const select = useUniverse((s) => s.selectItem);
  // eslint-disable-next-line react-hooks/incompatible-library -- expected: the virtualizer re-renders on scroll by design
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parent.current,
    estimateSize: () => ROW_H,
    overscan: 10,
  });
  useNearEnd(virtualizer.getVirtualItems().at(-1)?.index, items.length, onNearEnd);
  return (
    <div
      ref={parent}
      className="h-full overflow-y-auto"
      data-testid="items-list"
      role="listbox"
      aria-label="Items"
    >
      <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
        {virtualizer.getVirtualItems().map((row) => {
          const item = items[row.index]!;
          const snippet = hits.get(item.id)?.snippet;
          return (
            <div
              key={item.id}
              role="option"
              aria-selected={selected === item.id}
              data-testid="item-row"
              tabIndex={-1}
              onClick={() => select(item.id)}
              onDoubleClick={() => onOpen(item)}
              className={`absolute inset-x-0 flex cursor-default items-center gap-3 border-b border-hairline-1/60 px-4 transition-colors duration-100 ${
                selected === item.id ? 'bg-space-3/70' : 'hover:bg-space-2/60'
              }`}
              style={{ top: row.start, height: ROW_H }}
            >
              <TypeGlyph item={item} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm text-ink-1">{item.title}</span>
                {snippet && <Snippet text={snippet} />}
              </span>
              <span className="w-24 truncate text-xs text-ink-3">{ITEM_TYPES[item.type].label}</span>
              <span className="w-20 text-right text-xs text-ink-3">{formatDate(item.captured_at)}</span>
              <span className="w-16 text-right font-mono text-[11px] text-ink-3">
                {formatBytes(item.size_bytes)}
              </span>
              <PipelineDot status={item.pipeline_status} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Empty({ searching, query, trash }: { searching: boolean; query: string; trash: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center text-sm text-ink-3">
      {trash ? (
        <p>The trash is empty.</p>
      ) : searching ? (
        <>
          <Search className="size-6" aria-hidden />
          <p>Nothing found for “{query}”.</p>
          <p className="text-xs">
            Search reads titles, text, scanned text in images and, with an embedding model, meaning.
          </p>
        </>
      ) : (
        <>
          <Sparkles className="size-6 text-accent-2" aria-hidden />
          <p className="text-ink-2">Your vault is empty.</p>
          <p className="max-w-sm text-xs leading-relaxed">
            Drop files or folders anywhere in this window, add a watched folder in the Vault panel (V), or
            press the command-bar shortcut from any app to capture a note.
          </p>
        </>
      )}
    </div>
  );
}

export function ItemsView() {
  const api = useApi();
  const view = useUniverse((s) => s.view);
  const query = useUniverse((s) => s.query.trim());
  const trash = useUniverse((s) => s.showTrash);
  const selected = useUniverse((s) => s.selectedItemId);
  const select = useUniverse((s) => s.selectItem);
  const { items, total, searching, search, listing } = useItemsView();
  const section = useRef<HTMLElement>(null);
  const resultsFocusTick = useUniverse((s) => s.resultsFocusTick);
  const firstId = items[0]?.id;
  useEffect(() => {
    if (resultsFocusTick === handledResultsTick) return;
    section.current?.focus();
    if (!firstId) return; // results still loading: try again when they arrive
    handledResultsTick = resultsFocusTick;
    if (!useUniverse.getState().selectedItemId) useUniverse.getState().selectItem(firstId);
  }, [resultsFocusTick, firstId]);
  const hits = useMemo(() => new Map((search.data?.hits ?? []).map((h) => [h.item.id, h])), [search.data]);
  const open = (item: ItemSummary) => openItem(api, item.id);
  const loading = searching ? search.isFetching && !search.data : listing.isLoading;

  const { hasNextPage, isFetchingNextPage, fetchNextPage } = listing;
  const onNearEnd = useCallback(() => {
    if (!searching && hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [searching, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if ((e.target as HTMLElement).tagName === 'INPUT' || items.length === 0) return;
    const index = items.findIndex((i) => i.id === selected);
    const step = {
      ArrowDown: 1,
      ArrowUp: -1,
      ArrowRight: view === 'grid' ? 1 : 0,
      ArrowLeft: view === 'grid' ? -1 : 0,
    }[e.key];
    if (step) {
      e.preventDefault();
      const next = items[Math.max(0, Math.min(items.length - 1, index + step))];
      if (next) select(next.id);
    } else if (e.key === 'Enter' && index >= 0) {
      open(items[index]!);
    } else if (e.key === 'Delete' && index >= 0 && !trash) {
      trashItem(api, items[index]!.id, items[index]!.title);
    }
  };

  const semantic = searching ? (
    search.data?.semantic ? (
      <span
        className="flex items-center gap-1 text-[11px] text-accent-2"
        title="Keyword and meaning (hybrid search)"
      >
        <Sparkles className="size-3" aria-hidden /> by meaning too
      </span>
    ) : search.data?.semantic_note ? (
      <span className="max-w-xs truncate text-[11px] text-amber" title={search.data.semantic_note}>
        keyword only
      </span>
    ) : null
  ) : null;

  return (
    <section
      ref={section}
      aria-label="Vault items"
      tabIndex={0}
      onKeyDown={onKeyDown}
      data-testid="items-view"
      className="glass-solid hud-enter pointer-events-auto absolute top-16 right-[24rem] bottom-28 left-[17rem] flex flex-col overflow-hidden focus:outline-none"
    >
      <Toolbar count={total} searching={searching} semantic={semantic} />
      {searching && search.data && search.data.parsed.chips.length > 0 && (
        <div className="flex gap-1.5 px-4 pt-2 text-[11px] text-ink-3">
          Understood:
          {search.data.parsed.chips.map((chip) => (
            <span key={`${chip.kind}-${chip.value}`} className="rounded-full border border-hairline-2 px-2">
              {chip.kind}: {chip.label}
            </span>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1">
        {loading ? (
          <div className="flex h-full items-center justify-center text-ink-3">
            <LoaderCircle className="size-5 orb-spin" aria-label="Loading" />
          </div>
        ) : items.length === 0 ? (
          <Empty searching={searching} query={query} trash={trash} />
        ) : view === 'grid' ? (
          <GridView items={items} onOpen={open} onNearEnd={onNearEnd} />
        ) : (
          <ListView items={items} hits={hits} onOpen={open} onNearEnd={onNearEnd} />
        )}
      </div>
    </section>
  );
}
