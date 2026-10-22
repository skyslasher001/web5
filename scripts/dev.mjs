// `pnpm dev`: one command to start everything (SPEC §23).
//   uv sync → design tokens → desktop bundle → Vite dev server → Electron
// Electron main then starts the supervisor, which starts Core (and Ollama if installed).
// `pnpm start` passes --prod: uses the built UI over app:// instead of Vite.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { applyDotEnv, killCommand } from './dev-lib.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const prod = process.argv.includes('--prod');
// Anything after `--` goes to Electron, e.g. `pnpm dev -- --no-sandbox` when running as root on Linux.
const electronArgs = process.argv.includes('--') ? process.argv.slice(process.argv.indexOf('--') + 1) : [];
const win = process.platform === 'win32';
const UI_URL = 'http://127.0.0.1:5173';
const children = [];
const viaShell = new Set(); // children spawned with shell: true (on Windows: a cmd.exe in front of them)

function loadDotEnv() {
  const file = join(root, '.env');
  if (existsSync(file)) applyDotEnv(readFileSync(file, 'utf8'), process.env);
}

function step(label, cmd, args) {
  console.log(`\n▸ ${label}`);
  const result = spawnSync(cmd, args, { cwd: root, stdio: 'inherit', shell: win });
  if (result.error || result.status !== 0) {
    console.error(`✖ ${label} failed${result.error ? `: ${result.error.message}` : ''}`);
    if (result.error?.code === 'ENOENT')
      console.error(`  '${cmd}' was not found on PATH (see README → Setup).`);
    process.exit(1);
  }
}

async function waitFor(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`${url} did not come up within ${timeoutMs / 1000}s`);
}

function shutdown(code = 0) {
  for (const child of children) {
    if (child.exitCode !== null) continue;
    const tree = killCommand(child.pid, process.platform, viaShell.has(child));
    if (tree) spawnSync(tree[0], tree[1], { stdio: 'ignore' });
    else child.kill();
  }
  process.exit(code);
}

loadDotEnv();
step('Python environment (uv sync)', 'uv', ['sync']);
step('Design tokens', 'node', ['packages/design-tokens/build.mjs']);
step('Desktop bundle', 'node', ['apps/desktop/build.mjs']);
if (prod && !existsSync(join(root, 'apps', 'ui', 'dist', 'index.html'))) {
  step('UI build', 'pnpm', ['--filter', '@universe/ui', 'build']);
}

if (!prod) {
  console.log('\n▸ UI dev server (Vite)');
  const vite = spawn('pnpm', ['--filter', '@universe/ui', 'dev'], {
    cwd: root,
    stdio: 'inherit',
    shell: win,
  });
  children.push(vite);
  if (win) viaShell.add(vite);
  vite.on('exit', (code) => code && shutdown(code));
  await waitFor(UI_URL);
}

console.log('\n▸ Electron');
const electron = createRequire(join(root, 'apps', 'desktop', 'package.json'))('electron');
const app = spawn(electron, [...electronArgs, join(root, 'apps', 'desktop')], {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, UNIVERSE_UI_URL: prod ? '' : UI_URL },
});
children.push(app);
app.on('exit', (code) => shutdown(code ?? 0));
process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));
