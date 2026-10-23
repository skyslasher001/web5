import { afterEach, describe, expect, it, vi } from 'vitest';

describe('WebGL availability', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it('asks once and releases the probe context (Chromium caps live contexts at 16)', async () => {
    const loseContext = vi.fn();
    const gl = { getExtension: (name: string) => (name === 'WEBGL_lose_context' ? { loseContext } : null) };
    const createElement = vi.fn(() => ({ getContext: () => gl }));
    vi.stubGlobal('document', { createElement });
    const { webglAvailable } = await import('./webgl');
    expect(webglAvailable()).toBe(true);
    expect(webglAvailable()).toBe(true); // every Scene mount (3D ↔ Lite, a remount) asks again
    expect(createElement).toHaveBeenCalledTimes(1);
    expect(loseContext).toHaveBeenCalledTimes(1);
  });

  it('says no when the context cannot be made', async () => {
    vi.stubGlobal('document', { createElement: () => ({ getContext: () => null }) });
    const { webglAvailable } = await import('./webgl');
    expect(webglAvailable()).toBe(false);
  });
});
