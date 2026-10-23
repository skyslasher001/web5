import { beforeEach, describe, expect, it } from 'vitest';
import { useUniverse } from '../state/store';
import { attempt, startOnce } from './attempt';

describe('attempt', () => {
  beforeEach(() => useUniverse.setState({ activity: [] }));

  it('turns a failed action into a visible activity line instead of an unhandled rejection', async () => {
    attempt('Restart Core', Promise.reject(new Error('The supervisor is not running')));
    await new Promise((r) => setTimeout(r, 0));
    const [line] = useUniverse.getState().activity;
    expect(line).toMatchObject({ tone: 'bad', text: 'Restart Core failed: The supervisor is not running' });
  });

  it('stays quiet when the action succeeds', async () => {
    attempt('Open logs folder', Promise.resolve());
    await new Promise((r) => setTimeout(r, 0));
    expect(useUniverse.getState().activity).toEqual([]);
  });
});

describe('startOnce', () => {
  it('ignores a second start while the first is in flight (a double Ctrl+Enter starts one task)', async () => {
    const flag = { current: false };
    let release: () => void = () => {};
    let starts = 0;
    const start = () => {
      starts++;
      return new Promise<void>((r) => (release = r));
    };
    expect(startOnce(flag, start)).not.toBeNull();
    expect(startOnce(flag, start)).toBeNull();
    expect(starts).toBe(1);
    release();
    await new Promise((r) => setTimeout(r, 0));
    const failing = startOnce(flag, () => Promise.reject(new Error('Core is restarting')));
    expect(failing).not.toBeNull();
    failing?.catch(() => {}); // the caller reports it (attempt)
    await new Promise((r) => setTimeout(r, 0));
    expect(flag.current).toBe(false); // a failure frees it too
  });
});
