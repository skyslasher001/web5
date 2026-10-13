// Helpers the item viewers share: the file as a blob URL (media and PDFs need the session token, so a plain
// src can't load them) and safe Markdown.
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { useEffect, useState } from 'react';
import { useApi } from '../../lib/api-context';

/** The item's file as an object URL for <img>, <audio>, <video> and pdf.js; freed when the viewer closes. */
export function useFileUrl(id: string): { url: string | null; error: string | null } {
  const api = useApi();
  const [state, setState] = useState<{ id: string; url: string | null; error: string | null }>({
    id,
    url: null,
    error: null,
  });
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    api.itemFile(id).then(
      (blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setState({ id, url, error: null });
      },
      (err: unknown) => {
        if (!cancelled) setState({ id, url: null, error: err instanceof Error ? err.message : String(err) });
      },
    );
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [api, id]);
  return state.id === id ? { url: state.url, error: state.error } : { url: null, error: null };
}

const WIKILINK = /\[\[([^[\]|#\n]{1,200})(?:#[^[\]|\n]*)?(?:\|([^[\]\n]*))?\]\]/g;

/** Markdown → sanitized HTML. `[[Wikilinks]]` become links the viewer follows. */
export function renderMarkdown(source: string): string {
  const linked = source.replace(WIKILINK, (_m, target: string, label?: string) => {
    const safe = target.trim().replace(/"/g, '&quot;');
    return `<a href="#" data-wikilink="${safe}">${(label ?? target).trim()}</a>`;
  });
  const html = marked.parse(linked, { async: false, gfm: true, breaks: false });
  return DOMPurify.sanitize(html, { ADD_ATTR: ['data-wikilink'], FORBID_TAGS: ['style', 'form', 'input'] });
}
