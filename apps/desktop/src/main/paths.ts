// Where things live. Phase 1 always runs from a repo checkout (packaging is Phase 12), so data
// defaults to <repo>/.dev/ to keep real data out of development; set UNIVERSE_VAULT_DIR to use yours.
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { resolveBasePython, venvPython } from './python';

export interface AppPaths {
  repoRoot: string;
  dataDir: string;
  vaultDir: string;
  logDir: string;
  uiDist: string;
  safeModeDir: string;
  preload: string;
  supervisorScript: string;
  venvPython: string;
  basePython: string;
}

/** An environment variable's value, or undefined when it is unset or empty (`KEY=` in .env). */
export function envValue(env: NodeJS.ProcessEnv, key: string): string | undefined {
  const value = env[key]?.trim();
  return value ? value : undefined;
}

export function corePortFrom(env: NodeJS.ProcessEnv): number {
  return Number(envValue(env, 'UNIVERSE_CORE_PORT') ?? 47821);
}

export function resolvePaths(mainDir: string, env: NodeJS.ProcessEnv, platform: NodeJS.Platform): AppPaths {
  // mainDir is apps/desktop/dist
  const repoRoot = envValue(env, 'UNIVERSE_REPO_ROOT') ?? resolve(mainDir, '..', '..', '..');
  const dataDir = envValue(env, 'UNIVERSE_DATA_DIR') ?? join(repoRoot, '.dev', 'data');
  const readFile = (p: string) => (existsSync(p) ? readFileSync(p, 'utf8') : null);
  return {
    repoRoot,
    dataDir,
    vaultDir: envValue(env, 'UNIVERSE_VAULT_DIR') ?? join(repoRoot, '.dev', 'vault'),
    logDir: join(dataDir, 'logs'),
    uiDist: join(repoRoot, 'apps', 'ui', 'dist'),
    safeModeDir: join(mainDir, 'safe-mode'),
    preload: join(mainDir, 'preload.cjs'),
    supervisorScript: join(repoRoot, 'services', 'supervisor', 'run_supervisor.py'),
    venvPython: venvPython(repoRoot, platform),
    basePython: resolveBasePython(repoRoot, platform, readFile, existsSync),
  };
}
