/* global document, requestAnimationFrame */
// Phase 4 benchmark on YOUR machine (SPEC §24: 60 FPS at 50k items on recommended hardware, 30 FPS at 10k in
// Lite). Seeds a scratch vault with 50,000 synthetic items (unless you pass one), launches the real app on it
// and measures frame times per quality preset and layout, plus a camera flight.
//
//   pnpm build
//   pnpm bench:universe                 # seeds a temporary 50k vault (≈40 s), then measures
//   pnpm bench:universe -- D:\\Temp\\u50k  # or reuse a vault seeded with scripts/seed_universe.py
//
// It uses your normal Ollama (or none); nothing leaves the machine. Add --software to force software
// rendering (what CI has), which measures the CPU fallback, not your GPU.
import { _electron as electron } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '..');
const electronPath = createRequire(join(root, 'apps', 'desktop', 'package.json'))('electron');
const tmp = mkdtempSync(join(tmpdir(), 'universe-bench-'));
const given = process.argv.slice(2).find((a) => !a.startsWith('--'));
const vault = given ? resolve(given) : join(tmp, 'vault');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!existsSync(join(vault, '.universe', 'universe.db'))) {
  console.log(`Seeding 50,000 items into ${vault} …`);
  execFileSync('uv', ['run', '--quiet', 'python', 'scripts/seed_universe.py', vault, '--count', '50000'], {
    cwd: root,
    stdio: 'inherit',
  });
}

const app = await electron.launch({
  executablePath: electronPath,
  args: [
    ...(process.platform === 'linux' && process.getuid?.() === 0 ? ['--no-sandbox'] : []),
    ...(process.argv.includes('--software') ? ['--enable-unsafe-swiftshader'] : []),
    join(root, 'apps', 'desktop'),
  ],
  cwd: root,
  env: {
    ...process.env,
    UNIVERSE_VAULT_DIR: vault,
    UNIVERSE_DATA_DIR: join(tmp, 'data'),
    UNIVERSE_USER_DATA_DIR: join(tmp, 'profile'),
    UNIVERSE_UI_URL: '',
  },
});
let page = await app.firstWindow();
for (let k = 0; k < 60 && !app.windows().some((w) => !w.url().endsWith('#command-bar')); k++)
  await sleep(500);
page = app.windows().find((w) => !w.url().endsWith('#command-bar'));
await page.getByTestId('core-status').filter({ hasText: 'Core online' }).waitFor({ timeout: 120_000 });
const debug = (expr) => page.evaluate(`window.__universeDebug ? (${expr}) : null`);
for (let k = 0; k < 240; k++) {
  if (
    (await debug('window.__universeDebug.items()')) >= 50_000 &&
    (await debug('window.__universeDebug.layout()'))
  )
    break;
  await sleep(500);
}
const items = await debug('window.__universeDebug.items()');
const renderer = await page.evaluate(() => {
  const gl = document.createElement('canvas').getContext('webgl2');
  const ext = gl?.getExtension('WEBGL_debug_renderer_info');
  return gl && ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : 'unknown';
});
console.log(`\n${items} items · ${renderer}\n`);
// Never report a frame rate for a universe that isn't drawn (no WebGL, or the data didn't load).
if (!(items >= 50_000) || renderer === 'unknown') {
  console.error('The universe did not render: no WebGL, or the 50k items did not load. Nothing measured.');
  await app.close();
  process.exit(2);
}

async function frames() {
  const gaps = await page.evaluate(
    () =>
      new Promise((done) => {
        const out = [];
        let last = performance.now();
        const tick = (now) => {
          out.push(now - last);
          last = now;
          if (out.length < 200) requestAnimationFrame(tick);
          else done(out.slice(10));
        };
        requestAnimationFrame(tick);
      }),
  );
  gaps.sort((a, b) => a - b);
  return { median: gaps[Math.floor(gaps.length / 2)], p95: gaps[Math.floor(gaps.length * 0.95)] };
}

async function quality(q) {
  await page.getByRole('tab', { name: 'System' }).click();
  await page.getByTestId('quality').selectOption(q);
  await page.getByRole('tab', { name: 'Context' }).click();
  const view = q === 'lite' ? '[data-testid="lite-view"] canvas' : '[data-testid="universe-canvas"] canvas';
  await page.locator(view).first().waitFor({ timeout: 30_000 });
  await sleep(4000);
}

const rows = [];
const record = (label, f, budgetMs) => {
  const fps = 1000 / f.median;
  rows.push({ label, fps, p95: f.p95, pass: f.median <= budgetMs });
  console.log(
    `${label.padEnd(34)} ${fps.toFixed(0).padStart(4)} FPS (median ${f.median.toFixed(1)} ms, p95 ${f.p95.toFixed(1)} ms)` +
      `  ${f.median <= budgetMs ? 'PASS' : 'FAIL'}`,
  );
};

for (const q of ['high', 'balanced']) {
  await quality(q);
  for (const [key, layout] of [
    ['1', 'project'],
    ['3', 'time'],
    ['4', 'graph'],
  ]) {
    await page.keyboard.press(key);
    for (let k = 0; k < 120 && (await debug('window.__universeDebug.layout()')) !== layout; k++)
      await sleep(500);
    await page.keyboard.press(key === '1' ? '3' : '1'); // animate a transition while measuring…
    const f = await frames();
    await page.keyboard.press(key); // …then come back
    await sleep(1500);
    record(`3D ${q}, ${layout} (animating)`, f, 1000 / 58); // 60 FPS with a little jitter allowance
  }
}

// A camera flight: home, then fly to one item.
await quality('high');
await page.keyboard.press('h');
await sleep(1500);
await page.getByTestId('search-input').fill('01234');
await sleep(2500);
await page.getByTestId('search-input').press('Enter');
await sleep(2000);
const flight = await debug('window.__universeDebug.camera().lastFlight');
console.log(
  `Camera flight to an item              ${flight ? `${flight.actual} ms (planned ${flight.planned})` : 'n/a'}  ` +
    `${flight && flight.actual <= 1250 ? 'PASS' : 'FAIL'}`,
);
await page.getByTestId('search-input').fill('');

await quality('lite');
const view = page.getByTestId('lite-view');
const box = await view.boundingBox();
const panning = (async () => {
  for (let k = 0; k < 200; k++) {
    await page.mouse.wheel(0, k % 40 < 20 ? -80 : 80);
    await sleep(8);
  }
})();
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
const lite = await frames();
await panning;
record('Lite (2D), zooming', lite, 1000 / 29);

await app.close();
const failed = rows.filter((r) => !r.pass);
console.log(failed.length ? `\n${failed.length} measurement(s) below budget.` : '\nAll within budget.');
process.exit(failed.length ? 1 : 0);
