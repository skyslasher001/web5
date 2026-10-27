import { describe, expect, it } from 'vitest';
import { applyDotEnv, killCommand } from './dev-lib.mjs';

describe('pnpm dev helpers', () => {
  it('kills the whole process tree on Windows, where the child is cmd.exe (shell: true)', () => {
    expect(killCommand(4242, 'win32', true)).toEqual(['taskkill', ['/PID', '4242', '/T', '/F']]);
    expect(killCommand(4242, 'win32', false)).toBeNull(); // spawned directly (Electron): child.kill() reaches it
    expect(killCommand(4242, 'linux', false)).toBeNull();
    expect(killCommand(undefined, 'win32', true)).toBeNull(); // never started
  });

  it('reads .env without overriding the environment, and treats KEY= as unset', () => {
    const env = { KEEP: 'mine', EMPTY_IN_ENV: '' };
    applyDotEnv(
      [
        '# comment',
        'KEEP=theirs',
        'EMPTY_IN_ENV=/from/dotenv',
        'UNIVERSE_DATA_DIR=',
        'UNIVERSE_VAULT_DIR=""',
        'QUOTED="a=b"',
        '',
      ].join('\n'),
      env,
    );
    expect(env).toEqual({ KEEP: 'mine', EMPTY_IN_ENV: '/from/dotenv', QUOTED: 'a=b' });
  });
});
