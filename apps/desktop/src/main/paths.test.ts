import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { corePortFrom, resolvePaths } from './paths';

const mainDir = resolve('/repo/apps/desktop/dist');

describe('paths', () => {
  it('uses the environment when set', () => {
    const paths = resolvePaths(
      mainDir,
      { UNIVERSE_DATA_DIR: resolve('/d'), UNIVERSE_VAULT_DIR: resolve('/v') },
      'linux',
    );
    expect(paths.dataDir).toBe(resolve('/d'));
    expect(paths.vaultDir).toBe(resolve('/v'));
    expect(paths.logDir).toBe(join(resolve('/d'), 'logs'));
    expect(corePortFrom({ UNIVERSE_CORE_PORT: '48000' })).toBe(48000);
  });

  it('treats an empty value (KEY= in .env) as unset', () => {
    const env = {
      UNIVERSE_REPO_ROOT: '',
      UNIVERSE_DATA_DIR: '',
      UNIVERSE_VAULT_DIR: ' ',
      UNIVERSE_CORE_PORT: '',
    };
    const paths = resolvePaths(mainDir, env, 'linux');
    expect(paths.repoRoot).toBe(resolve('/repo'));
    expect(paths.dataDir).toBe(join(resolve('/repo'), '.dev', 'data'));
    expect(paths.vaultDir).toBe(join(resolve('/repo'), '.dev', 'vault'));
    expect(corePortFrom(env)).toBe(47821);
    expect(corePortFrom({})).toBe(47821);
  });
});
