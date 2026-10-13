// "Save clipboard to inbox": main reads the clipboard (the renderer can't without a permission prompt)
// and posts it to Core's capture API with the session token.
import type { ClipboardCaptureResult } from '@universe/shared-types';

export interface ClipboardSource {
  readText(): Promise<string>;
  /** PNG bytes of the clipboard image, or null if there is no image. */
  readImagePng(): Promise<Buffer | null>;
}

/** Electron 44's clipboard is asynchronous and W3C-shaped: items carrying MIME types. */
export interface AsyncClipboard {
  readText(): Promise<string>;
  read(): Promise<Array<{ types: readonly string[]; getType(type: string): Promise<unknown> }>>;
}

export function clipboardSource(clipboard: AsyncClipboard): ClipboardSource {
  return {
    readText: () => clipboard.readText(),
    readImagePng: async () => {
      for (const item of await clipboard.read()) {
        if (item.types.includes('image/png')) {
          const blob = (await item.getType('image/png')) as Blob;
          return Buffer.from(await blob.arrayBuffer());
        }
      }
      return null;
    },
  };
}

export async function captureClipboard(
  source: ClipboardSource,
  coreUrl: string,
  token: string,
  fetchImpl: typeof fetch,
  now: () => Date = () => new Date(),
): Promise<ClipboardCaptureResult> {
  const headers = { Authorization: `Bearer ${token}` };
  let png: Buffer | null = null;
  try {
    png = await source.readImagePng();
    if (png && png.length > 0) {
      const stamp = now().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const form = new FormData();
      form.append('files', new Blob([new Uint8Array(png)], { type: 'image/png' }), `screenshot-${stamp}.png`);
      form.append('source', 'clipboard');
      const response = await fetchImpl(`${coreUrl}/api/v1/capture/files`, {
        method: 'POST',
        headers,
        body: form,
      });
      return response.ok
        ? { kind: 'image', ok: true, message: 'Image saved to the inbox' }
        : { kind: 'image', ok: false, message: `Core refused the image (HTTP ${response.status})` };
    }
    const text = (await source.readText()).trim();
    if (!text) return { kind: 'empty', ok: false, message: 'The clipboard is empty' };
    const response = await fetchImpl(`${coreUrl}/api/v1/capture`, {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 200_000), source: 'clipboard' }),
    });
    return response.ok
      ? { kind: 'text', ok: true, message: 'Clipboard saved to the inbox' }
      : { kind: 'text', ok: false, message: `Core refused the text (HTTP ${response.status})` };
  } catch {
    return { kind: png ? 'image' : 'text', ok: false, message: 'Core is not reachable' };
  }
}
