import { describe, expect, it, vi } from 'vitest';
import { captureClipboard, clipboardSource, type ClipboardSource } from './clipboardCapture';
import { ringPixels } from './trayPixels';

const ok = () => new Response('{}', { status: 201 });
const source = (text: string, png: Buffer | null = null): ClipboardSource => ({
  readText: async () => text,
  readImagePng: async () => png,
});

describe('clipboard capture', () => {
  it('posts text as a note with the session token', async () => {
    const fetchImpl = vi.fn(async () => ok());
    const result = await captureClipboard(
      source('  https://example.com/plat  '),
      'http://127.0.0.1:47821',
      'tok',
      fetchImpl,
    );
    expect(result).toEqual({ kind: 'text', ok: true, message: 'Clipboard saved to the inbox' });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://127.0.0.1:47821/api/v1/capture');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
    expect(JSON.parse(init.body as string)).toEqual({
      text: 'https://example.com/plat',
      source: 'clipboard',
    });
  });

  it('uploads an image as a png file', async () => {
    const fetchImpl = vi.fn(async () => ok());
    const result = await captureClipboard(
      source('', Buffer.from([0x89, 0x50, 0x4e, 0x47])),
      'http://core',
      'tok',
      fetchImpl,
      () => new Date('2026-10-13T09:41:00Z'),
    );
    expect(result.ok && result.kind === 'image').toBe(true);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://core/api/v1/capture/files');
    const file = (init.body as FormData).get('files') as File;
    expect(file.name).toBe('screenshot-2026-10-13T09-41-00.png');
  });

  it('reports an empty clipboard and an unreachable Core', async () => {
    const empty = await captureClipboard(source(' '), 'x', 't', vi.fn());
    expect(empty).toEqual({ kind: 'empty', ok: false, message: 'The clipboard is empty' });
    const down = await captureClipboard(
      source('hi'),
      'x',
      't',
      vi.fn(async () => {
        throw new TypeError('fetch failed');
      }),
    );
    expect(down.ok).toBe(false);
  });

  it("reads a png from Electron's W3C-style clipboard items", async () => {
    const png = new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' });
    const reader = clipboardSource({
      readText: async () => '',
      read: async () => [
        { types: ['text/html'], getType: async () => new Blob(['<b>x</b>']) },
        { types: ['image/png'], getType: async () => png },
      ],
    });
    expect([...((await reader.readImagePng()) ?? [])]).toEqual([1, 2, 3]);
    const textOnly = clipboardSource({ readText: async () => 'x', read: async () => [] });
    expect(await textOnly.readImagePng()).toBeNull();
  });
});

describe('tray icon', () => {
  it('draws an opaque ring and core with a transparent gap between', () => {
    const size = 32;
    const px = ringPixels(size);
    const alpha = (x: number, y: number) => px[(y * size + x) * 4 + 3]!;
    expect(alpha(16, 16)).toBe(255); // core dot
    expect(alpha(0, 0)).toBe(0); // corner
    expect(alpha(16, 2)).toBe(255); // ring
    expect(alpha(16, 8)).toBe(0); // gap between ring and core
  });
});
