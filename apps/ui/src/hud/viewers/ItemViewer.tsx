// Item zoom (SPEC §7): a glass card unfolds over the dimmed universe with the viewer for the item's type, or
// a galaxy's dashboard. Esc (or the close button) returns to the System zoom.
import 'highlight.js/styles/github-dark-dimmed.css';
import { tokens } from '@universe/design-tokens';
import type { ItemType } from '@universe/shared-types';
import { ExternalLink, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useApi } from '../../lib/api-context';
import { hueHex } from '../../lib/colors';
import { ITEM_TYPES } from '../../lib/itemTypes';
import { itemShown, useItem, useProjects } from '../../lib/queries';
import { openItem } from '../../lib/vaultActions';
import { useUniverse } from '../../state/store';
import { styleFor } from '../../universe/scene/types';
import { Button } from '../ui';
import { CodeViewer, MediaViewer, PdfViewer, PhotoViewer, TextViewer } from './MediaViewers';
import { NoteViewer } from './NoteViewer';
import { ProjectDashboard } from './ProjectDashboard';

const MARKDOWN = /\.(md|markdown)$/i;

function Body({ id }: { id: string }) {
  const item = useItem(id);
  const data = itemShown(id, item.data);
  if (!data) return <p className="text-sm text-ink-3">{item.isError ? 'This item is gone.' : 'Loading…'}</p>;
  switch (data.type) {
    case 'note':
    case 'idea':
    case 'transcript':
      return MARKDOWN.test(data.path) ? <NoteViewer id={id} /> : <TextViewer item={data} />;
    case 'photo':
    case 'screenshot':
      return <PhotoViewer item={data} />;
    case 'song':
    case 'audio':
    case 'voice_memo':
    case 'video':
      return <MediaViewer item={data} />;
    case 'pdf':
      return <PdfViewer item={data} />;
    case 'code_file':
      return <CodeViewer item={data} />;
    default:
      return <TextViewer item={data} />;
  }
}

export function ItemViewer() {
  const api = useApi();
  const itemId = useUniverse((s) => s.viewerItemId);
  const projectId = useUniverse((s) => s.dashboardProjectId);
  const close = useUniverse((s) => s.closeViewer);
  const item = itemShown(itemId, useItem(itemId).data);
  const projects = useProjects();
  const project = projectId ? projects.data?.find((p) => p.id === projectId) : undefined;
  const card = useRef<HTMLDivElement>(null);
  const open = itemId !== null || project !== undefined;
  useEffect(() => {
    if (open) card.current?.focus();
  }, [open, itemId, projectId]);
  // Viewing an item counts as opening it: it brightens (SPEC §7), and viewing one right after another fires
  // the pathway between them (SPEC §10). A failure here only costs that signal, so it's logged, not shown.
  useEffect(() => {
    if (!itemId) return;
    api.openItem(itemId).catch((err: unknown) => console.warn('Could not record the view', err));
  }, [api, itemId]);
  if (!open) return null;

  const type = item?.type as ItemType | undefined;
  const style = type ? ITEM_TYPES[type] : null;
  const Icon = style?.Icon;
  const color = project ? hueHex(project.color_token) : style ? tokens.color[style.hue] : tokens.color.slate;
  const title = project?.name ?? item?.title ?? '…';
  const subtitle = project
    ? `Galaxy · ${project.item_count} items · ${project.status}`
    : type
      ? `${style!.label} · ${styleFor(type, null).body}`
      : '';
  return (
    <div
      className="pointer-events-auto absolute inset-0 grid place-items-center bg-space-0/55 p-6"
      style={{ zIndex: 'var(--z-panel)' }}
      onClick={(e) => e.target === e.currentTarget && close()}
    >
      <div
        ref={card}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onKeyDown={(e) => {
          // Esc closes the viewer from anywhere inside it, the editor included.
          if (e.key === 'Escape') {
            e.stopPropagation();
            e.nativeEvent.stopImmediatePropagation();
            close();
          }
        }}
        className="glass-strong hud-enter flex h-[min(46rem,calc(100vh-7rem))] w-[min(72rem,calc(100vw-3rem))] flex-col gap-4 p-5 outline-none"
        data-testid="item-viewer"
      >
        <header className="flex items-center gap-3">
          <span
            className="grid size-8 place-items-center rounded-full"
            style={{ background: `${color}22`, color }}
          >
            {Icon ? <Icon className="size-4" aria-hidden /> : null}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate font-display text-lg text-ink-1" data-testid="viewer-title">
              {title}
            </h2>
            <p className="text-xs text-ink-3">{subtitle}</p>
          </div>
          {itemId && (
            <Button onClick={() => openItem(api, itemId)} title="Open with its default app">
              <ExternalLink className="size-3.5" aria-hidden /> Open
            </Button>
          )}
          <button
            type="button"
            onClick={close}
            aria-label="Close (Esc)"
            className="text-ink-3 hover:text-ink-1"
          >
            <X className="size-5" aria-hidden />
          </button>
        </header>
        <div className="min-h-0 flex-1">
          {project ? (
            <ProjectDashboard project={project} />
          ) : itemId ? (
            <Body key={itemId} id={itemId} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
