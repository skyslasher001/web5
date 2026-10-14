// Notes (SPEC §7): a Markdown editor with live preview and backlinks. Saving records a new version; if the
// note changed elsewhere meanwhile, nothing is overwritten and you're asked to reload.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { NoteContent } from '@universe/shared-types';
import { Link2, Save, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { ApiError } from '../../lib/api';
import { useApi } from '../../lib/api-context';
import { attempt } from '../../lib/attempt';
import { useDebounced } from '../../lib/queries';
import { refreshItemQueries } from '../../lib/queryClient';
import { useUniverse } from '../../state/store';
import { useScene } from '../../universe/scene/sceneData';
import { Button, inputClass } from '../ui';
import { renderMarkdown } from './viewerUtils';

function Backlinks({ id }: { id: string }) {
  const api = useApi();
  const client = useQueryClient();
  const links = useQuery({ queryKey: ['links', id], queryFn: () => api.itemLinks(id) });
  const [query, setQuery] = useState('');
  const q = useDebounced(query.trim(), 200);
  const found = useQuery({
    queryKey: ['link-search', q],
    queryFn: () => api.search({ q, limit: 6 }),
    enabled: q.length > 1,
  });
  const open = useUniverse((s) => s.openViewer);
  const reload = () => client.invalidateQueries({ queryKey: ['links', id] });
  const data = links.data;
  return (
    <aside className="space-y-3 text-xs" aria-label="Links">
      <div>
        <p className="mb-1 text-ink-3">Backlinks ({data?.incoming.length ?? 0})</p>
        <ul className="space-y-0.5" data-testid="backlinks">
          {data?.incoming.map((l) => (
            <li key={l.id}>
              <button
                type="button"
                onClick={() => open(l.item.id)}
                className="text-left text-ink-2 hover:text-accent"
              >
                {l.item.title}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="mb-1 text-ink-3">Links ({data?.outgoing.length ?? 0})</p>
        <ul className="space-y-0.5">
          {data?.outgoing.map((l) => (
            <li key={l.id} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => open(l.item.id)}
                className="flex-1 truncate text-left text-ink-2 hover:text-accent"
              >
                {l.item.title}
              </button>
              {l.kind === 'manual' && (
                <button
                  type="button"
                  title="Unlink"
                  onClick={() => attempt('Unlink', api.removeLink(l.id).then(reload))}
                >
                  <X className="size-3 text-ink-3 hover:text-danger" aria-label="Unlink" />
                </button>
              )}
            </li>
          ))}
          {data?.unresolved.map((t) => (
            <li key={t} className="text-ink-3" title="No item has this title yet">
              [[{t}]]
            </li>
          ))}
        </ul>
      </div>
      <div className="space-y-1">
        <p className="flex items-center gap-1 text-ink-3">
          <Link2 className="size-3" aria-hidden /> Link to…
        </p>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search for an item"
          aria-label="Link to an item"
          className={`${inputClass} w-full`}
        />
        <ul className="space-y-0.5">
          {found.data?.hits
            .filter((h) => h.item.id !== id)
            .map((h) => (
              <li key={h.item.id}>
                <button
                  type="button"
                  className="w-full truncate text-left text-ink-2 hover:text-accent"
                  onClick={() =>
                    attempt(
                      'Link',
                      api.addLink(id, h.item.id).then(() => {
                        setQuery('');
                        return reload();
                      }),
                    )
                  }
                >
                  {h.item.title}
                </button>
              </li>
            ))}
        </ul>
      </div>
    </aside>
  );
}

export function NoteViewer({ id }: { id: string }) {
  const api = useApi();
  const note = useQuery({ queryKey: ['note', id], queryFn: () => api.noteContent(id), staleTime: Infinity });
  const [draft, setDraft] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const body = draft ?? note.data?.body ?? '';
  const preview = useMemo(() => renderMarkdown(body), [body]);
  const dirty = draft !== null && draft !== note.data?.body;
  const setViewerDirty = useUniverse((s) => s.setViewerDirty);
  useEffect(() => {
    setViewerDirty(dirty);
    return () => setViewerDirty(false);
  }, [dirty, setViewerDirty]);

  const save = () => {
    const base = note.data;
    if (!base || !dirty || saving) return;
    setSaving(true);
    api
      .saveNote(id, draft ?? '', base.version)
      .then((saved: NoteContent) => {
        note.refetch();
        setDraft(saved.body);
        setConflict(null);
        void refreshItemQueries();
        useUniverse.getState().addNotice('good', `Saved version ${saved.version}`);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 409) setConflict(err.message);
        else
          useUniverse.getState().addNotice('bad', `Save failed: ${err instanceof Error ? err.message : err}`);
      })
      .finally(() => setSaving(false));
  };

  // Ctrl+S saves (the editor keeps focus).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        save();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const followWikilink = (target: string) => {
    const scene = useScene.getState().scene;
    const lower = target.toLowerCase();
    const index = scene.titles.findIndex((t) => t.toLowerCase() === lower);
    if (index >= 0) useUniverse.getState().openViewer(scene.ids[index]!);
    else useUniverse.getState().addNotice('info', `No item called “${target}” yet`);
  };

  if (note.isError) {
    return (
      <p className="text-sm text-danger">
        {note.error instanceof Error ? note.error.message : 'Could not load'}
      </p>
    );
  }
  return (
    <div className="grid h-full min-h-0 grid-cols-[1fr_1fr_12rem] gap-4">
      <div className="flex min-h-0 flex-col gap-2">
        <textarea
          value={body}
          onChange={(e) => setDraft(e.target.value)}
          spellCheck
          aria-label="Note (Markdown)"
          className={`${inputClass} min-h-0 flex-1 resize-none font-mono text-[13px] leading-relaxed`}
          data-testid="note-editor"
        />
        <div className="flex items-center gap-2 text-xs text-ink-3">
          <Button tone="primary" onClick={save} disabled={!dirty || saving} testid="note-save">
            <Save className="size-3.5" aria-hidden /> Save
          </Button>
          <span>
            {dirty ? 'Unsaved changes · Ctrl+S' : note.data ? `Version ${note.data.version}` : 'Loading…'}
          </span>
        </div>
        {conflict && (
          <p role="alert" className="text-xs text-danger">
            {conflict}{' '}
            <button
              type="button"
              className="underline"
              onClick={() => void note.refetch().then(() => setDraft(null))}
            >
              Reload (your edits are discarded)
            </button>
          </p>
        )}
      </div>
      <div
        className="markdown min-h-0 overflow-y-auto rounded-md bg-space-1/60 p-3 text-sm leading-relaxed text-ink-1 select-text"
        data-testid="note-preview"
        // Sanitized by DOMPurify in renderMarkdown.
        dangerouslySetInnerHTML={{ __html: preview }}
        onClick={(e) => {
          const link = (e.target as HTMLElement).closest('a');
          if (!link) return;
          e.preventDefault();
          const wiki = link.getAttribute('data-wikilink');
          if (wiki) followWikilink(wiki);
        }}
      />
      <Backlinks id={id} />
    </div>
  );
}
