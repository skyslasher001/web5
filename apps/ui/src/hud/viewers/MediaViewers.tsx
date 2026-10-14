// Photos, audio and video, PDFs, code and plain documents (SPEC §7 item viewers). pdf.js and highlight.js
// load only when one of these viewers needs them.
import { useQuery } from '@tanstack/react-query';
import { tokens } from '@universe/design-tokens';
import type { Item } from '@universe/shared-types';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { useApi } from '../../lib/api-context';
import { useThumbnail } from '../../lib/queries';
import { useUniverse } from '../../state/store';
import { Button } from '../ui';
import { AskCore } from './shared';
import { useFileUrl } from './viewerUtils';

function Fields({ fields }: { fields: [string, unknown][] }) {
  const shown = fields.filter(([, v]) => v !== undefined && v !== null && v !== '');
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {shown.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-3">{k}</dt>
          <dd className="truncate font-mono text-ink-1">{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function SimilarThumb({ id, title }: { id: string; title: string }) {
  const url = useThumbnail(id, true);
  const open = useUniverse((s) => s.openViewer);
  return (
    <button
      type="button"
      onClick={() => open(id)}
      title={title}
      className="size-16 overflow-hidden rounded-md bg-space-2"
    >
      {url ? <img src={url} alt={title} className="size-full object-cover" /> : null}
    </button>
  );
}

export function PhotoViewer({ item }: { item: Item }) {
  const api = useApi();
  const { url, error } = useFileUrl(item.id);
  const text = useQuery({ queryKey: ['item-text', item.id], queryFn: () => api.itemText(item.id, 600) });
  const similar = useQuery({ queryKey: ['similar', item.id], queryFn: () => api.similarItems(item.id, 8) });
  const meta = item.metadata as Record<string, unknown>;
  return (
    <div className="grid h-full min-h-0 grid-cols-[1fr_16rem] gap-4">
      <div className="grid min-h-0 place-items-center rounded-md bg-space-0/70">
        {url ? (
          <img
            src={url}
            alt={item.title}
            className="max-h-full max-w-full object-contain"
            data-testid="photo"
          />
        ) : (
          <p className="text-xs text-ink-3">{error ?? 'Loading…'}</p>
        )}
      </div>
      <div className="min-h-0 space-y-3 overflow-y-auto">
        <Fields
          fields={[
            ['Taken', meta.taken_at ?? item.captured_at.slice(0, 10)],
            ['Camera', [meta.camera_make, meta.camera_model].filter(Boolean).join(' ')],
            ['Size', meta.width ? `${meta.width} × ${meta.height}` : undefined],
            ['Lens', meta.lens],
            [
              'Location',
              typeof meta.lat === 'number'
                ? `${meta.lat.toFixed(4)}, ${Number(meta.lon).toFixed(4)}`
                : undefined,
            ],
          ]}
        />
        {text.data?.text && <p className="text-xs leading-relaxed text-ink-2">{text.data.text}</p>}
        {similar.data && similar.data.length > 0 && (
          <div>
            <p className="mb-1 text-xs text-ink-3">Similar</p>
            <div className="flex flex-wrap gap-1.5">
              {similar.data.map((s) => (
                <SimilarThumb key={s.id} id={s.id} title={s.title} />
              ))}
            </div>
          </div>
        )}
        <AskCore
          id={item.id}
          title={item.title}
          prompt={`Describe the photo “${item.title}” (item id ${item.id}).`}
        />
      </div>
    </div>
  );
}

/** A waveform drawn from the decoded audio (Web Audio), with the playhead. */
function Waveform({
  blob,
  audio,
  onSeek,
}: {
  blob: Blob;
  audio: RefObject<HTMLAudioElement | null>;
  onSeek: (fraction: number) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [peaks, setPeaks] = useState<Float32Array | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const ctx = new AudioContext();
    blob
      .arrayBuffer()
      .then((buf) => ctx.decodeAudioData(buf))
      .then((decoded) => {
        const data = decoded.getChannelData(0);
        const buckets = 600;
        const out = new Float32Array(buckets);
        const size = Math.floor(data.length / buckets) || 1;
        for (let b = 0; b < buckets; b++) {
          let max = 0;
          for (let i = b * size; i < (b + 1) * size && i < data.length; i += 16)
            max = Math.max(max, Math.abs(data[i]!));
          out[b] = max;
        }
        if (!cancelled) setPeaks(out);
      })
      .catch((err: unknown) => {
        if (!cancelled) setFailed(`No waveform: ${err instanceof Error ? err.message : String(err)}`);
      })
      .finally(() => void ctx.close());
    return () => {
      cancelled = true;
    };
  }, [blob]);
  useEffect(() => {
    let raf = 0;
    const draw = () => {
      const c = canvas.current;
      const g = c?.getContext('2d');
      if (c && g && peaks) {
        g.clearRect(0, 0, c.width, c.height);
        const a = audio.current;
        const played = a && a.duration ? a.currentTime / a.duration : 0;
        const w = c.width / peaks.length;
        peaks.forEach((p, i) => {
          const h = Math.max(1, p * c.height * 0.9);
          g.fillStyle = i / peaks.length < played ? tokens.color.rose : tokens.color.slate;
          g.fillRect(i * w, (c.height - h) / 2, Math.max(1, w - 0.5), h);
        });
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [peaks, audio]);
  if (failed) return <p className="text-xs text-ink-3">{failed}</p>;
  return (
    <canvas
      ref={canvas}
      width={1200}
      height={120}
      className="h-24 w-full cursor-pointer"
      aria-label="Waveform: click to seek"
      data-testid="waveform"
      data-ready={peaks ? 'true' : 'false'}
      onClick={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        onSeek((e.clientX - rect.left) / rect.width);
      }}
    />
  );
}

export function MediaViewer({ item }: { item: Item }) {
  const { url, blob, error } = useFileUrl(item.id);
  const audio = useRef<HTMLAudioElement>(null);
  const meta = item.metadata as Record<string, unknown>;
  const isVideo = item.type === 'video';
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {!url || !blob ? (
        <p className="text-xs text-ink-3">{error ?? 'Loading…'}</p>
      ) : isVideo ? (
        <video src={url} controls className="min-h-0 flex-1 rounded-md bg-black" data-testid="video" />
      ) : (
        <>
          <Waveform
            blob={blob}
            audio={audio}
            onSeek={(fraction) => {
              const a = audio.current;
              if (a && a.duration) a.currentTime = fraction * a.duration;
            }}
          />
          <audio ref={audio} src={url} controls className="w-full" data-testid="audio" />
        </>
      )}
      <Fields
        fields={[
          ['Duration', typeof meta.duration_s === 'number' ? `${Math.round(meta.duration_s)} s` : undefined],
          ['Artist', meta.artist],
          ['Album', meta.album],
          ['BPM', meta.bpm],
          ['Key', meta.key],
        ]}
      />
      {isVideo && <p className="text-xs text-ink-3">Synced transcripts arrive with Voice (Phase 7).</p>}
    </div>
  );
}

export function PdfViewer({ item }: { item: Item }) {
  const { blob, error } = useFileUrl(item.id);
  const holder = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(0);
  const [failed, setFailed] = useState<string | null>(null);
  const doc = useRef<{ getPage(n: number): Promise<unknown>; numPages: number } | null>(null);

  useEffect(() => {
    if (!blob) return;
    let cancelled = false;
    // Destroying the loading task frees the document and its worker thread when the viewer closes.
    let task: { destroy(): Promise<void> } | null = null;
    (async () => {
      const pdfjs = await import('pdfjs-dist');
      pdfjs.GlobalWorkerOptions.workerSrc = new URL(
        'pdfjs-dist/build/pdf.worker.min.mjs',
        import.meta.url,
      ).toString();
      const data = new Uint8Array(await blob.arrayBuffer()); // bytes, not a blob: URL (CSP connect-src)
      if (cancelled) return;
      const loading = pdfjs.getDocument({ data });
      task = loading;
      const loaded = await loading.promise;
      if (cancelled) return;
      doc.current = loaded as unknown as typeof doc.current;
      setPages(loaded.numPages);
      setPage(1);
    })().catch((err: unknown) => {
      if (!cancelled) setFailed(err instanceof Error ? err.message : String(err));
    });
    return () => {
      cancelled = true;
      doc.current = null;
      void task?.destroy();
    };
  }, [blob]);

  useEffect(() => {
    const d = doc.current;
    const el = holder.current;
    if (!d || !el || !pages) return;
    let cancelled = false;
    (async () => {
      type PdfPage = {
        getViewport(o: { scale: number }): { width: number; height: number };
        render(o: { canvas: HTMLCanvasElement; viewport: unknown }): { promise: Promise<void> };
      };
      const p = (await d.getPage(page)) as PdfPage;
      if (cancelled) return;
      const base = p.getViewport({ scale: 1 });
      const viewport = p.getViewport({ scale: Math.min(2, (el.clientWidth - 16) / base.width) });
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.className = 'mx-auto rounded-sm bg-white';
      await p.render({ canvas, viewport }).promise;
      if (!cancelled) el.replaceChildren(canvas);
    })().catch((err: unknown) => setFailed(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [page, pages]);

  return (
    <div className="grid h-full min-h-0 grid-cols-[1fr_14rem] gap-4">
      <div className="min-h-0 overflow-y-auto rounded-md bg-space-0/70 p-2">
        {(failed || error || !pages) && (
          <p className="text-xs text-ink-3" data-testid="pdf-status">
            {failed ?? error ?? 'Loading…'}
          </p>
        )}
        {/* pdf.js pages go here; React renders nothing inside, so replacing them can't remove a message */}
        <div ref={holder} data-testid="pdf-pages" />
      </div>
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs text-ink-2">
          <Button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}>
            <ChevronLeft className="size-3.5" aria-label="Previous page" />
          </Button>
          <span data-testid="pdf-page">{pages ? `Page ${page} of ${pages}` : '…'}</span>
          <Button onClick={() => setPage(Math.min(pages, page + 1))} disabled={page >= pages}>
            <ChevronRight className="size-3.5" aria-label="Next page" />
          </Button>
        </div>
        <AskCore
          id={item.id}
          title={item.title}
          prompt={`Read the PDF “${item.title}” (item id ${item.id}) and summarize its key points.`}
        />
      </div>
    </div>
  );
}

const EXT_LANG: Record<string, string> = {
  py: 'python', ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript', rs: 'rust', go: 'go',
  java: 'java', cs: 'csharp', cpp: 'cpp', c: 'c', h: 'c', rb: 'ruby', php: 'php', sh: 'bash', ps1: 'powershell',
  sql: 'sql', json: 'json', yaml: 'yaml', yml: 'yaml', toml: 'ini', css: 'css', html: 'xml', md: 'markdown',
}; // prettier-ignore

export function CodeViewer({ item }: { item: Item }) {
  const api = useApi();
  const [html, setHtml] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ default: hljs }, blob] = await Promise.all([
        import('highlight.js/lib/common'),
        api.itemFile(item.id),
      ]);
      const text = (await blob.text()).slice(0, 400_000);
      const ext = item.path.split('.').pop()?.toLowerCase() ?? '';
      const lang = EXT_LANG[ext];
      const result =
        lang && hljs.getLanguage(lang) ? hljs.highlight(text, { language: lang }) : hljs.highlightAuto(text);
      if (!cancelled) setHtml(result.value); // highlight.js escapes the source text
    })().catch((err: unknown) => !cancelled && setFailed(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [api, item.id, item.path]);
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <pre className="hljs min-h-0 flex-1 overflow-auto rounded-md bg-space-0/80 p-3 font-mono text-[12px] leading-relaxed select-text">
        {html === null ? (
          <span className="text-ink-3">{failed ?? 'Loading…'}</span>
        ) : (
          <code dangerouslySetInnerHTML={{ __html: html }} data-testid="code" />
        )}
      </pre>
    </div>
  );
}

export function TextViewer({ item }: { item: Item }) {
  const api = useApi();
  const text = useQuery({
    queryKey: ['item-text', item.id, 'full'],
    queryFn: () => api.itemText(item.id, 200_000),
  });
  const meta = item.metadata as Record<string, unknown>;
  return (
    <div className="grid h-full min-h-0 grid-cols-[1fr_14rem] gap-4">
      <div className="min-h-0 overflow-y-auto rounded-md bg-space-1/60 p-3 text-sm leading-relaxed whitespace-pre-wrap text-ink-1 select-text">
        {text.data ? text.data.text || 'No text was extracted from this file.' : 'Loading…'}
        {text.data?.truncated && (
          <p className="mt-2 text-xs text-ink-3">(Shortened: open it for the rest.)</p>
        )}
      </div>
      <div className="space-y-3">
        <Fields
          fields={[
            ['Pages', meta.pages],
            ['Author', meta.author],
            ['URL', meta.url],
            ['Words', typeof meta.text_chars === 'number' ? Math.round(meta.text_chars / 5.5) : undefined],
          ]}
        />
        <AskCore id={item.id} title={item.title} />
      </div>
    </div>
  );
}
