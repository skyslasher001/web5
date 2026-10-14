// The right panel for a selected item: preview, metadata, projects, tags, pipeline status and actions.
import type { Item, ItemStage } from '@universe/shared-types';
import { tokens } from '@universe/design-tokens';
import { useQuery } from '@tanstack/react-query';
import {
  ArchiveRestore,
  ExternalLink,
  Eye,
  FolderSearch,
  Pin,
  PinOff,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { hueHex } from '../lib/colors';
import { formatBytes } from '../lib/format';
import { formatDate, ITEM_TYPES } from '../lib/itemTypes';
import { useItem, useProjects } from '../lib/queries';
import { openItem, revealItem, trashItem } from '../lib/vaultActions';
import { useUniverse } from '../state/store';
import { ItemVisual } from '../views2d/ItemVisual';
import { Dot, SectionTitle } from './ui';

const STAGE_LABEL: Record<string, string> = {
  metadata: 'Metadata',
  extract: 'Text',
  thumbnail: 'Thumbnail',
  ocr: 'Text in image',
  caption: 'Caption',
  transcribe: 'Transcript',
  embed: 'Meaning (embeddings)',
  sidecar: 'Sidecar file',
};

const STAGE_COLOR: Record<ItemStage['status'], string> = {
  pending: tokens.color.slate,
  running: tokens.color.amber,
  done: tokens.color.green,
  failed: tokens.color.danger,
  skipped: tokens.color.slate,
};

function Action({
  onClick,
  label,
  children,
  danger = false,
  testid,
}: {
  onClick: () => void;
  label: string;
  children: ReactNode;
  danger?: boolean;
  testid?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      className={`flex items-center gap-1.5 rounded-md border border-hairline-2 px-2.5 py-1 text-xs transition-colors duration-150 ${
        danger
          ? 'text-ink-2 hover:border-danger/60 hover:text-danger'
          : 'text-ink-2 hover:border-accent/60 hover:text-ink-1'
      }`}
    >
      {children}
      {label}
    </button>
  );
}

function Stages({ stages }: { stages: ItemStage[] }) {
  return (
    <ul className="space-y-1" data-testid="item-stages">
      {stages.map((stage) => (
        <li key={stage.stage} className="text-xs" title={stage.error ?? stage.detail ?? undefined}>
          <span className="flex items-center gap-2">
            <Dot color={STAGE_COLOR[stage.status]} pulse={stage.status === 'running'} />
            <span className="flex-1 text-ink-2">{STAGE_LABEL[stage.stage] ?? stage.stage}</span>
            <span className={stage.status === 'failed' ? 'text-danger' : 'text-ink-3'}>{stage.status}</span>
          </span>
          {(stage.status === 'failed' || stage.status === 'skipped') && (stage.error || stage.detail) && (
            <span className="mt-0.5 ml-4 block text-[11px] leading-snug text-ink-3">
              {stage.error ?? stage.detail}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function Tags({ item }: { item: Item }) {
  const api = useApi();
  const refresh = useUniverse((s) => s.refreshItems);
  const [draft, setDraft] = useState('');
  const save = (tags: string[]) => attempt('Update tags', api.patchItem(item.id, { tags }).then(refresh));
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {item.tags.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-1 rounded-full border border-hairline-2 px-2 py-0.5 text-xs text-ink-2"
        >
          #{tag}
          <button
            type="button"
            aria-label={`Remove tag ${tag}`}
            onClick={() => save(item.tags.filter((t) => t !== tag))}
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && draft.trim()) {
            save([...item.tags, draft.trim().replace(/^#/, '')]);
            setDraft('');
          }
        }}
        placeholder="+ tag"
        aria-label="Add a tag"
        className="w-20 bg-transparent text-xs text-ink-2 placeholder:text-ink-3 focus:outline-none"
      />
    </div>
  );
}

function Projects({ item }: { item: Item }) {
  const api = useApi();
  const projects = useProjects();
  const refresh = useUniverse((s) => s.refreshItems);
  const all = projects.data ?? [];
  const member = all.filter((p) => item.project_ids.includes(p.id));
  const others = all.filter((p) => !item.project_ids.includes(p.id));
  const patch = (body: { add_projects?: string[]; remove_projects?: string[] }) =>
    attempt('Update galaxies', api.patchItem(item.id, body).then(refresh));
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {member.map((p) => (
        <span
          key={p.id}
          className="flex items-center gap-1.5 rounded-full border border-hairline-2 px-2 py-0.5 text-xs text-ink-2"
        >
          <Dot color={hueHex(p.color_token)} />
          {p.name}
          <button
            type="button"
            aria-label={`Remove from ${p.name}`}
            onClick={() => patch({ remove_projects: [p.id] })}
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
      {others.length > 0 && (
        <select
          aria-label="Add to a galaxy"
          value=""
          onChange={(e) => e.target.value && patch({ add_projects: [e.target.value] })}
          className="rounded-md border border-hairline-2 bg-space-2 px-1.5 py-0.5 text-xs text-ink-3"
        >
          <option value="">+ galaxy</option>
          {others.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

export function ItemPanel({ id }: { id: string }) {
  const api = useApi();
  const item = useItem(id);
  const select = useUniverse((s) => s.selectItem);
  const refresh = useUniverse((s) => s.refreshItems);
  const text = useQuery({
    queryKey: ['item-text', id, item.data?.current_version],
    queryFn: () => api.itemText(id, 1500),
    enabled: !!item.data && !item.data.trashed_at,
  });
  const data = item.data;
  if (item.isError) return <p className="text-sm text-danger">This item is gone.</p>;
  if (!data) return <p className="text-xs text-ink-3">Loading…</p>;
  const style = ITEM_TYPES[data.type];
  const trashed = !!data.trashed_at;
  return (
    <div className="fade-enter space-y-5" data-testid="item-panel" key={id}>
      <div>
        <ItemVisual item={data} className="h-40 w-full rounded-lg border border-hairline-1 bg-space-1" />
        <p className="mt-3 flex items-center gap-1.5 text-xs" style={{ color: tokens.color[style.hue] }}>
          <style.Icon className="size-3.5" aria-hidden /> {style.label}
          {trashed && <span className="text-danger">· in the trash</span>}
        </p>
        <h2
          className="mt-1 font-display text-lg leading-snug font-semibold break-words"
          data-testid="item-title"
        >
          {data.title}
        </h2>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {trashed ? (
          <>
            <Action label="Restore" onClick={() => attempt('Restore', api.restoreItem(id).then(refresh))}>
              <ArchiveRestore className="size-3.5" aria-hidden />
            </Action>
            <Action
              danger
              label="Delete forever"
              onClick={() => {
                if (
                  window.confirm(
                    `Delete “${data.title}” permanently? The file, its versions, thumbnail and index entries are removed. Backups keep it until they're pruned.`,
                  )
                )
                  attempt(
                    'Delete',
                    api.deleteItem(id, true).then(() => {
                      select(null);
                      refresh();
                    }),
                  );
              }}
            >
              <Trash2 className="size-3.5" aria-hidden />
            </Action>
          </>
        ) : (
          <>
            <Action label="View" onClick={() => useUniverse.getState().openViewer(id)} testid="view-item">
              <Eye className="size-3.5" aria-hidden />
            </Action>
            <Action label="Open" onClick={() => openItem(api, id)}>
              <ExternalLink className="size-3.5" aria-hidden />
            </Action>
            <Action label="Show in folder" onClick={() => revealItem(api, id)}>
              <FolderSearch className="size-3.5" aria-hidden />
            </Action>
            <Action
              label={data.pinned ? 'Unpin' : 'Pin'}
              onClick={() => attempt('Pin', api.patchItem(id, { pinned: !data.pinned }).then(refresh))}
            >
              {data.pinned ? (
                <PinOff className="size-3.5" aria-hidden />
              ) : (
                <Pin className="size-3.5" aria-hidden />
              )}
            </Action>
            <Action
              label="Reprocess"
              onClick={() => attempt('Reprocess', api.reprocessItem(id).then(refresh))}
            >
              <RefreshCw className="size-3.5" aria-hidden />
            </Action>
            <Action danger label="Trash" onClick={() => trashItem(api, id, data.title)}>
              <Trash2 className="size-3.5" aria-hidden />
            </Action>
          </>
        )}
      </div>
      <section>
        <SectionTitle>Galaxies</SectionTitle>
        <Projects item={data} />
      </section>
      <section>
        <SectionTitle>Tags</SectionTitle>
        <Tags item={data} />
      </section>
      {text.data && text.data.text && (
        <section>
          <SectionTitle>Text</SectionTitle>
          <p
            className="max-h-48 overflow-y-auto text-xs leading-relaxed whitespace-pre-wrap text-ink-2"
            data-testid="item-text"
          >
            {text.data.text}
            {text.data.truncated ? '…' : ''}
          </p>
        </section>
      )}
      <section>
        <SectionTitle>Processing</SectionTitle>
        <Stages stages={data.stages} />
      </section>
      <section>
        <SectionTitle>Details</SectionTitle>
        <dl className="space-y-1 text-xs">
          {(
            [
              ['Captured', formatDate(data.captured_at)],
              ['Added', formatDate(data.created_at)],
              ['Size', formatBytes(data.size_bytes)],
              ['Version', `${data.current_version} of ${data.versions.length}`],
              ['Opened', `${data.open_count}×`],
              ['From', data.source ? data.source.kind.replace('_', ' ') : '—'],
              ['File', data.path],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3">
              <dt className="text-ink-3">{label}</dt>
              <dd className="truncate text-right font-mono text-ink-2" title={String(value)}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      <button type="button" onClick={() => select(null)} className="text-xs text-ink-3 hover:text-ink-2">
        ← Back
      </button>
    </div>
  );
}
