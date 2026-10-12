// The app:// protocol that serves the built renderer, with a strict Content-Security-Policy.
import { extname, normalize, resolve, sep } from 'node:path';

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.map': 'application/json',
};

export function contentType(file: string): string {
  return TYPES[extname(file).toLowerCase()] ?? 'application/octet-stream';
}

/** Maps app://universe/<path> to a file inside `root`; null for other hosts or path traversal. */
export function resolveAppFile(root: string, requestUrl: string): string | null {
  const url = new URL(requestUrl);
  if (url.host !== 'universe') return null;
  let pathname = decodeURIComponent(url.pathname);
  if (pathname === '/' || pathname === '') pathname = '/index.html';
  const base = resolve(root);
  const file = resolve(base, normalize('.' + pathname));
  return file === base || file.startsWith(base + sep) ? file : null;
}

export function buildCsp(corePort: number): string {
  const core = `127.0.0.1:${corePort}`;
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' http://${core} ws://${core}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'none'",
  ].join('; ');
}
