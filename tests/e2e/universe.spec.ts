// Phase 4 "done when" (SPEC §25): a 50k-item seed dataset hits the FPS budget and search flies the camera
// to results. Seeds an empty scratch vault with scripts/seed_universe.py, then drives the real app.
//
// FPS budget (SPEC §24): 60 FPS at 50k items on recommended hardware, 30 FPS at 10k items in 2D Lite.
// Both budgets are for real graphics hardware. This CI runner renders in software (SwiftShader), so here
// the numbers are measured and printed, and asserted only when a GPU renders. `pnpm bench:universe` gives
// the figures on your PC.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..');
const electronPath = createRequire(join(root, 'apps', 'desktop', 'package.json'))(
  'electron',
) as unknown as string;
const ITEMS = 50_000;

test.describe.configure({ timeout: 300_000 });

function freePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() =>
        typeof address === 'object' && address ? resolvePort(address.port) : reject(new Error('no port')),
      );
    });
  });
}

let app: ElectronApplication;
let page: Page;
let fake: ChildProcess;
let tmp: string;
let netLog: string;

interface Debug {
  items(): number;
  layout(): string | null;
  results(): number;
  pulses(): number;
  camera(): {
    position: number[];
    target: number[];
    flying: boolean;
    lastFlight: { planned: number; actual: number } | null;
  };
}

const debug = <T>(fn: (d: Debug) => T): Promise<T> =>
  page.evaluate(
    (src) =>
      new Function('d', `return (${src})(d)`)(
        (window as unknown as { __universeDebug: Debug }).__universeDebug,
      ),
    fn.toString(),
  ) as Promise<T>;

/** Frame times while something animates: median and p95 in ms (130 frames, or 8 s if frames are slow). */
async function frameTimes(): Promise<{ median: number; p95: number; frames: number }> {
  const gaps = await page.evaluate(
    () =>
      new Promise<number[]>((done) => {
        const out: number[] = [];
        const started = performance.now();
        let last = started;
        const tick = (now: number) => {
          out.push(now - last);
          last = now;
          if (out.length < 130 && now - started < 8_000) requestAnimationFrame(tick);
          else done(out.length > 20 ? out.slice(10) : out.slice(1));
        };
        requestAnimationFrame(tick);
      }),
  );
  const sorted = [...gaps].sort((a, b) => a - b);
  return {
    median: sorted[Math.floor(sorted.length / 2)]!,
    p95: sorted[Math.floor(sorted.length * 0.95)]!,
    frames: gaps.length,
  };
}

/** Back to the universe at home: no viewer, no selection, no search. */
async function reset(): Promise<void> {
  await page.getByTestId('search-input').fill('');
  for (let k = 0; k < 4; k++) await page.keyboard.press('Escape');
  await expect(page.getByTestId('item-viewer')).toHaveCount(0);
}

/** Switch the universe's quality preset from System → Display (each test sets the mode it needs). */
async function useQuality(quality: 'high' | 'lite'): Promise<void> {
  await page.getByRole('tab', { name: 'System' }).click();
  await page.getByTestId('quality').selectOption(quality);
  await page.getByRole('tab', { name: 'Context' }).click();
  const view =
    quality === 'lite'
      ? '[data-testid="lite-view"] canvas.sigma-nodes'
      : '[data-testid="universe-canvas"] canvas';
  await expect(page.locator(view)).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => debug((d) => d.layout()), { timeout: 60_000 }).not.toBeNull();
}

async function core<T>(method: string, path: string, body?: unknown): Promise<T> {
  return page.evaluate(
    async ({ method, path, body }) => {
      const config = await window.universe!.getConfig();
      const response = await fetch(`${config.coreUrl}/api/v1${path}`, {
        method,
        headers: { Authorization: `Bearer ${config.token}`, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`${method} ${path}: HTTP ${response.status}`);
      return (await response.json()) as T;
    },
    { method, path, body },
  );
}

test.beforeAll(async () => {
  tmp = mkdtempSync(join(tmpdir(), 'universe-50k-'));
  netLog = join(tmp, 'netlog.json');
  const vault = join(tmp, 'vault');
  const ollamaPort = await freePort();
  const corePort = await freePort();
  fake = spawn(
    'uv',
    [
      'run',
      '--quiet',
      'python',
      'tests/support/fake_ollama.py',
      '--port',
      String(ollamaPort),
      '--delay-ms',
      '15',
    ],
    { cwd: root, stdio: ['ignore', 'pipe', 'inherit'] },
  );
  await new Promise<void>((ready, fail) => {
    createInterface({ input: fake.stdout! }).once('line', () => ready());
    fake.once('exit', (code) => fail(new Error(`fake ollama exited (${code})`)));
  });
  // The fake embedder is fake-embed:latest with digest "bbb" and 1024 dimensions (tests/support/fake_ollama.py).
  const seeded = execFileSync(
    'uv',
    [
      'run', '--quiet', 'python', 'scripts/seed_universe.py', vault,
      '--count', String(ITEMS), '--embedder', 'fake-embed:latest@bbb', '--dim', '1024',
    ],
    { cwd: root, encoding: 'utf8' },
  ); // prettier-ignore
  console.log(seeded.trim().split('\n')[0]);
  app = await electron.launch({
    executablePath: electronPath,
    args: [
      ...(process.platform === 'linux' ? ['--no-sandbox'] : []),
      '--enable-unsafe-swiftshader',
      `--log-net-log=${netLog}`,
      join(root, 'apps', 'desktop'),
    ],
    cwd: root,
    env: {
      ...process.env,
      UNIVERSE_DATA_DIR: join(tmp, 'data'),
      UNIVERSE_VAULT_DIR: vault,
      UNIVERSE_USER_DATA_DIR: join(tmp, 'profile'),
      UNIVERSE_CORE_PORT: String(corePort),
      UNIVERSE_OLLAMA_URL: `http://127.0.0.1:${ollamaPort}`,
      UNIVERSE_MANAGE_OLLAMA: '0',
      UNIVERSE_UI_URL: '',
    },
  });
  await expect
    .poll(() => app.windows().some((w) => !w.url().endsWith('#command-bar')), { timeout: 30_000 })
    .toBe(true);
  page = app.windows().find((w) => !w.url().endsWith('#command-bar'))!;
  await expect(page.getByTestId('core-status')).toHaveText(/Core online/, { timeout: 90_000 });
});

test.afterAll(async () => {
  await app?.close().catch(() => {});
  fake?.kill();
});

test('50k items stream into the universe', async () => {
  const started = Date.now();
  await expect.poll(() => debug((d) => d?.items?.() ?? 0), { timeout: 60_000 }).toBe(ITEMS);
  await expect.poll(() => debug((d) => d.layout()), { timeout: 60_000 }).toBe('project');
  console.log(`50k items loaded and laid out in ${((Date.now() - started) / 1000).toFixed(1)} s`);
  await page.screenshot({ path: 'test-results/universe-50k.png' });
});

test('the FPS budget at 50k items', async () => {
  const renderer = await page.evaluate(() => {
    const gl = document.createElement('canvas').getContext('webgl2');
    const ext = gl?.getExtension('WEBGL_debug_renderer_info');
    return gl && ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : 'unknown';
  });
  const software = /swiftshader|llvmpipe|software/i.test(renderer);
  console.log(`renderer: ${renderer}`);

  // Lite (what Auto picks here): zoom in and out with the real mouse wheel, so every frame redraws.
  await useQuality('lite');
  const box = (await page.getByTestId('lite-view').boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const zooming = (async () => {
    const until = Date.now() + 8_000;
    for (let k = 0; Date.now() < until; k++) {
      await page.mouse.wheel(0, k % 30 < 15 ? -80 : 80);
      await page.waitForTimeout(10);
    }
  })();
  const lite = await frameTimes();
  await zooming;
  console.log(`Lite, ${ITEMS} items: median ${lite.median.toFixed(1)} ms, p95 ${lite.p95.toFixed(1)} ms`);
  if (!software) expect(lite.median).toBeLessThan(34); // ≥ 30 FPS (SPEC §24, minimum hardware / Lite)

  // 3D at the High preset, while a layout transition animates every item.
  await useQuality('high');
  await expect.poll(() => debug((d) => d.layout()), { timeout: 60_000 }).toBe('project');
  await page.keyboard.press('3');
  const threeD = await frameTimes();
  console.log(
    `3D High, ${ITEMS} items: median ${threeD.median.toFixed(1)} ms, p95 ${threeD.p95.toFixed(1)} ms`,
  );
  await page.keyboard.press('1');
  if (!software) expect(threeD.median).toBeLessThan(17.5); // 60 FPS on a real GPU (SPEC §24)
});

test('search flies the camera to the results', async () => {
  await reset();
  await useQuality('high');
  await expect.poll(() => debug((d) => d.layout()), { timeout: 60_000 }).toBe('project');
  await page.keyboard.press('h');
  await expect.poll(() => debug((d) => d.camera().flying), { timeout: 10_000 }).toBe(false);
  const home = await debug((d) => d.camera());

  // A seeded item's unique number finds exactly that item: Enter flies to it (System zoom).
  const search = page.getByTestId('search-input');
  await search.fill('01234');
  await expect.poll(() => debug((d) => d.results()), { timeout: 30_000 }).toBeGreaterThan(0);
  await expect(page.getByTestId('result-badge').first()).toBeVisible();
  await expect.poll(() => debug((d) => d.camera().flying), { timeout: 10_000 }).toBe(false); // framed
  const before = await debug((d) => d.camera().lastFlight);
  await search.press('Enter');
  await expect(page.getByTestId('zoom-level')).toHaveText('System');
  await expect
    .poll(async () => {
      const c = await debug((d) => d.camera());
      return !c.flying && c.lastFlight !== null && c.lastFlight !== before;
    }, { timeout: 15_000 })
    .toBe(true); // prettier-ignore
  const there = await debug((d) => d.camera());
  const moved = Math.hypot(...there.target.map((v, i) => v - home.target[i]!));
  const distance = Math.hypot(...there.position.map((v, i) => v - there.target[i]!));
  const { planned, actual } = there.lastFlight!;
  console.log(
    `flew ${moved.toFixed(0)} units: planned ${planned} ms, took ${actual} ms; now ${distance.toFixed(1)} from the item`,
  );
  expect(moved).toBeGreaterThan(20);
  expect(distance).toBeLessThan(25); // close up: the item and its neighbours
  expect(planned).toBeGreaterThanOrEqual(600);
  expect(planned).toBeLessThanOrEqual(1_200); // SPEC §24: camera flight ≤ 1.2 s
  // Finishes on the first frame after the planned time; software rendering here draws ~4 frames a second.
  expect(actual).toBeLessThan(planned + 400);
  await expect(page.getByTestId('breadcrumb')).toContainText('01234');
  await page.screenshot({ path: 'test-results/universe-search-flight.png' });

  // A broad search forms a numbered constellation and frames it.
  await page.keyboard.press('Escape');
  await search.fill('water');
  await expect.poll(() => debug((d) => d.results()), { timeout: 30_000 }).toBeGreaterThanOrEqual(9);
  await expect(page.getByTestId('result-badge').nth(8)).toBeVisible();
  await page.screenshot({ path: 'test-results/universe-constellation.png' });
  await search.fill('');
});

test('layouts switch with 1–4 and the semantic layout comes from Core', async () => {
  await reset();
  for (const [key, layout] of [
    ['3', 'time'],
    ['4', 'graph'],
    ['2', 'semantic'],
    ['1', 'project'],
  ] as const) {
    await page.keyboard.press(key);
    await expect.poll(() => debug((d) => d.layout()), { timeout: 90_000 }).toBe(layout);
  }
});

test('the note viewer edits Markdown safely and follows links', async () => {
  await reset();
  await useQuality('high');
  const target = await core<{ item_id: string }>('POST', '/capture', {
    title: 'Parcel map',
    text: 'The parcel map for the lake lot.',
  });
  const note = await core<{ item_id: string }>('POST', '/capture', {
    title: 'Viewer check',
    text: 'See [[Parcel map]].\n\n<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>',
  });
  await expect.poll(() => debug((d) => d.items()), { timeout: 30_000 }).toBeGreaterThan(ITEMS);
  await page.getByTestId('search-input').fill('Viewer check');
  await expect.poll(() => debug((d) => d.results()), { timeout: 30_000 }).toBeGreaterThan(0);
  await page.getByTestId('search-input').press('Enter');
  await page.getByTestId('view-item').click();
  const preview = page.getByTestId('note-preview');
  await expect(preview).toContainText('Parcel map');
  expect(await preview.locator('script, [onerror]').count()).toBe(0);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();

  // Edit and save: a new version.
  await page.getByTestId('note-editor').fill('Edited in the viewer. See [[Parcel map]].');
  await page.getByTestId('note-save').click();
  // The viewer shows the new version at once, and a notice confirms the save.
  await expect(page.getByTestId('item-viewer').getByText('Version 2', { exact: true })).toBeVisible();
  await expect(page.getByText('Saved version 2')).toBeVisible();
  const item = await core<{ versions: unknown[] }>('GET', `/items/${note.item_id}`);
  expect(item.versions).toHaveLength(2);

  // Follow the wikilink to the other note's viewer.
  await preview.getByText('Parcel map').click();
  await expect(page.getByTestId('viewer-title')).toHaveText('Parcel map');
  // Moving from one note to the linked one fires the pathway: a signal pulse travels the link (SPEC §10).
  await expect.poll(() => debug((d) => d.pulses()), { timeout: 15_000 }).toBeGreaterThan(0);
  // A fresh editor for the linked note (regression: the previous note's draft used to carry over).
  await expect(page.getByTestId('note-editor')).toHaveValue(/The parcel map for the lake lot/);
  await expect(page.getByTestId('backlinks')).toContainText('Viewer check');
  expect(target.item_id).toBeTruthy();
  // Single-key shortcuts don't act behind the viewer (regression: Z used to close it, losing a draft).
  await page.getByTestId('viewer-title').click();
  await page.keyboard.press('z');
  await page.keyboard.press('g');
  await expect(page.getByTestId('item-viewer')).toBeVisible();
  // Esc closes the viewer even from inside the editor.
  await page.getByTestId('note-editor').click();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('item-viewer')).toHaveCount(0);

  // Changed elsewhere (an agent, another editor) while closed: reopening shows the new text, not a cached
  // copy (regression: a reopened note showed stale content, and saving it then conflicted).
  const current = await core<{ version: number }>('GET', `/items/${target.item_id}/content`);
  await core('PUT', `/items/${target.item_id}/content`, {
    body: 'Rewritten by an agent.',
    base_version: current.version,
  });
  await page.getByTestId('search-input').fill('Parcel map');
  await expect.poll(() => debug((d) => d.results()), { timeout: 30_000 }).toBeGreaterThan(0);
  await page.getByTestId('search-input').press('Enter');
  await page.getByTestId('view-item').click();
  await expect(page.getByTestId('viewer-title')).toHaveText('Parcel map');
  await expect(page.getByTestId('note-editor')).toHaveValue(/^Rewritten by an agent\.\s*$/); // files end in a newline
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('item-viewer')).toHaveCount(0);
});

test('PDFs and songs open in their viewers under the security policy', async () => {
  // Regression: pdf.js and the waveform read the file through a blob: URL, which the CSP's connect-src
  // blocks in the packaged app (served over app://), so PDFs failed and songs had no waveform.
  await reset();
  const dir = join(tmp, 'media');
  execFileSync(
    'uv',
    [
      'run', '--quiet', 'python', '-c',
      'import sys; from pathlib import Path; from tests.support.files import write_pdf, write_wav; ' +
        'd = Path(sys.argv[1]); d.mkdir(); ' +
        'write_pdf(d / "zephyr-survey.pdf", ["Zephyr survey page one", "Zephyr survey page two"]); ' +
        'write_wav(d / "zephyr-song.wav", title="Zephyr Song", artist="Tester", seconds=1.0)',
      dir,
    ],
    { cwd: root },
  ); // prettier-ignore
  await core('POST', '/ingest/paths', { paths: [dir] });
  for (const [query, check] of [
    ['zephyr-survey', 'pdf'],
    ['Zephyr Song', 'song'],
  ] as const) {
    await expect
      .poll(
        async () =>
          (await core<{ hits: unknown[] }>('GET', `/search?q=${encodeURIComponent(query)}`)).hits.length,
        { timeout: 60_000 },
      )
      .toBeGreaterThan(0);
    await page.getByTestId('search-input').fill(query);
    await expect.poll(() => debug((d) => d.results()), { timeout: 30_000 }).toBeGreaterThan(0);
    await page.getByTestId('search-input').press('Enter');
    await page.getByTestId('view-item').click();
    if (check === 'pdf') {
      await expect(page.getByTestId('pdf-page')).toHaveText('Page 1 of 2', { timeout: 30_000 });
      await expect(page.getByTestId('pdf-pages').locator('canvas')).toHaveCount(1);
    } else {
      await expect(page.getByTestId('waveform')).toHaveAttribute('data-ready', 'true', { timeout: 30_000 });
    }
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('item-viewer')).toHaveCount(0);
    await page.getByTestId('search-input').fill('');
  }
});

test('a galaxy dashboard keeps goals', async () => {
  await reset();
  await page.getByTestId('galaxy-list').getByText('DevMind').click();
  await page.getByTestId('open-dashboard').click();
  await expect(page.getByTestId('dashboard')).toBeVisible();
  await page.getByLabel('New goal').fill('Ship the universe');
  await page.getByLabel('New goal').press('Enter');
  await expect(page.getByTestId('goals')).toContainText('Ship the universe');
  await page.screenshot({ path: 'test-results/universe-dashboard.png' });
  await page.keyboard.press('Escape');
});

test('nothing leaves the machine while the universe runs', async () => {
  await app.close();
  expect(existsSync(netLog)).toBe(true);
  const urls = readFileSync(netLog, 'utf8').match(/"(?:https?|wss?):\/\/[^"/\\]+/g) ?? [];
  const external = [...new Set(urls.map((u) => u.slice(1)))].filter(
    (u) => !/^(https?|wss?):\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(u),
  );
  expect(external).toEqual([]);
});
