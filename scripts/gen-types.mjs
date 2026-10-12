// Regenerates packages/shared-types from the backend: OpenAPI → TypeScript, event catalog → TypeScript.
// `node scripts/gen-types.mjs --check` fails when the committed files are stale (CI).
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtempSync, readFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = join(root, 'packages', 'shared-types');
const check = process.argv.includes('--check');
const out = check ? mkdtempSync(join(tmpdir(), 'shared-types-')) : pkg;
mkdirSync(join(out, 'src'), { recursive: true });

// No shell anywhere: shell-joined arguments break on paths with spaces (e.g. a Windows profile folder).
const run = (cmd, args) => execFileSync(cmd, args, { cwd: root, stdio: 'inherit' });
const require = createRequire(import.meta.url);
const openapiCli = join(dirname(require.resolve('openapi-typescript/package.json')), 'bin', 'cli.js');
run('uv', ['run', '--quiet', 'python', '-m', 'universe_core.schema_export', out]);
run(process.execPath, [openapiCli, join(out, 'openapi.json'), '-o', join(out, 'src', 'api.ts')]);

if (check) {
  const files = ['openapi.json', 'src/api.ts', 'src/events.ts'];
  const stale = files.filter(
    (f) => readFileSync(join(out, f), 'utf8') !== readFileSync(join(pkg, f), 'utf8'),
  );
  rmSync(out, { recursive: true, force: true });
  if (stale.length) {
    console.error(`shared types are stale (${stale.join(', ')}). Run: pnpm gen:types`);
    process.exit(1);
  }
  console.log('shared types are up to date');
}
