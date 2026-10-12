import { describe, expect, it } from 'vitest';
import { ApiError, CoreApi } from './api';

describe('CoreApi', () => {
  it('sends the session token and surfaces problem details', async () => {
    const calls: [string, RequestInit][] = [];
    const api = new CoreApi('http://127.0.0.1:1', 'tok', async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return new Response(JSON.stringify({ detail: 'Agents are disabled in safe mode' }), { status: 503 });
    });
    await expect(api.sendChat('hi', 'c1')).rejects.toMatchObject({
      status: 503,
      message: 'Agents are disabled in safe mode',
    });
    expect(calls[0]![0]).toBe('http://127.0.0.1:1/api/v1/chat');
    expect((calls[0]![1].headers as Record<string, string>).Authorization).toBe('Bearer tok');
  });

  it('reports an unreachable Core as status 0', async () => {
    const api = new CoreApi('http://127.0.0.1:1', 'tok', async () => {
      throw new TypeError('fetch failed');
    });
    const error = await api.vitals().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);
  });
});
