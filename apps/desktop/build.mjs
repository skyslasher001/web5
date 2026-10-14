// Bundles Electron main and preload with esbuild and copies the static safe-mode page.
import { context, build } from 'esbuild';
import { cpSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const watch = process.argv.includes('--watch');
const common = {
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node22',
  external: ['electron'],
  sourcemap: true,
  logLevel: 'info',
};
const entries = [
  { entryPoints: [join(here, 'src/main/index.ts')], outfile: join(here, 'dist/main.cjs') },
  // Sandboxed preloads must be a single CommonJS file that only requires 'electron'.
  { entryPoints: [join(here, 'src/preload/index.ts')], outfile: join(here, 'dist/preload.cjs') },
];

mkdirSync(join(here, 'dist'), { recursive: true });
cpSync(join(here, 'src/safe-mode'), join(here, 'dist/safe-mode'), { recursive: true });

if (watch) {
  for (const entry of entries) await (await context({ ...common, ...entry })).watch();
} else {
  await Promise.all(entries.map((entry) => build({ ...common, ...entry })));
}
