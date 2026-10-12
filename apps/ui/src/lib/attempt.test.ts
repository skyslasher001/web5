import { beforeEach, describe, expect, it } from 'vitest';
import { useUniverse } from '../state/store';
import { attempt } from './attempt';

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
