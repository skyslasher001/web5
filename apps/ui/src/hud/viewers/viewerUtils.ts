// Helpers the item viewers share: the file as a blob URL (media and PDFs need the session token, so a plain
// src can't load them) and safe Markdown.
import DOMPurify from 'dompurify';
import { Marked, type TokenizerAndRendererExtension } from 'marked';
import { useEffect, useState } from 'react';
import { useApi } from '../../lib/api-context';

/**
 * The item's file as an object URL for <img>, <audio> and <video>, freed when the viewer closes, plus the
 * Blob itself for code that reads the bytes (pdf.js, the waveform). Reading a blob: URL with fetch or XHR
 * falls under the CSP's connect-src, which deliberately allows only Core.
 */
export function useFileUrl(id: string): { url: string | null; blob: Blob | null; error: string | null } {
  const api = useApi();
  const [state, setState] = useState<{
    id: string;
    url: string | null;
    blob: Blob | null;
    error: string | null;
  }>({ id, url: null, blob: null, error: null });
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    api.itemFile(id).then(
      (blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setState({ id, url, blob, error: null });
      },
      (err: unknown) => {
        if (!cancelled)
          setState({ id, url: null, blob: null, error: err instanceof Error ? err.message : String(err) });
      },
    );
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [api, id]);
  return state.id === id
    ? { url: state.url, blob: state.blob, error: state.error }
    : { url: null, blob: null, error: null };
}

/** The editor's draft once a save of `sent` lands: kept only if the owner typed more meanwhile. */
export function draftAfterSave(current: string | null, sent: string): string | null {
  return current === sent ? null : current;
}

const WIKILINK = /^\[\[([^[\]|#\n]{1,200})(?:#[^[\]|\n]*)?(?:\|([^[\]\n]*))?\]\]/;

const escapeHtml = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// `[[Target]]` and `[[Target|label]]` as an inline Markdown token, so code spans and fenced code keep them
// as literal text, and both parts are escaped.
const wikilink: TokenizerAndRendererExtension = {
  name: 'wikilink',
  level: 'inline',
  start: (src) => src.indexOf('[['),
  tokenizer(src) {
    const m = WIKILINK.exec(src);
    if (!m) return undefined;
    const target = m[1]!.trim();
    return { type: 'wikilink', raw: m[0], target, label: (m[2] ?? '').trim() || target };
  },
  renderer: (token) =>
    `<a href="#" data-wikilink="${escapeHtml(String(token.target))}">${escapeHtml(String(token.label))}</a>`,
};

const markdown = new Marked({ gfm: true, breaks: false, extensions: [wikilink] });

/** Markdown → HTML, before sanitizing (exported for tests). */
export function markdownToHtml(source: string): string {
  return markdown.parse(source, { async: false });
}

/** Markdown → sanitized HTML. `[[Wikilinks]]` become links the viewer follows. */
export function renderMarkdown(source: string): string {
  return DOMPurify.sanitize(markdownToHtml(source), {
    ADD_ATTR: ['data-wikilink'],
    FORBID_TAGS: ['style', 'form', 'input'],
  });
}
