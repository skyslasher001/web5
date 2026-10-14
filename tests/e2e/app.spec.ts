// Phase 1 "done when": launch the app, chat with streaming replies, kill the backend and watch it
// auto-restart. Phase 2: add files, find them by keyword and by meaning, use the command bar.
// Phase 3: "find my notes about X, summarize them, and link them to project Y" with an approval and a full
// audit trail (needs the protected-core patch; without it the panels say agents chat without tools).
// Uses the real Electron app, supervisor, Core and pipeline workers; only the model server is a stand-in.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
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

async function startFakeOllama(port: number): Promise<ChildProcess> {
  const child = spawn(
    'uv',
    ['run', '--quiet', 'python', 'tests/support/fake_ollama.py', '--port', String(port), '--delay-ms', '15'],
    // No shell: on Windows `uv` resolves to uv.exe directly, and kill() then stops the server itself
    // instead of an intermediate cmd.exe (which would leave the fake server running).
    { cwd: root, stdio: ['ignore', 'pipe', 'inherit'] },
  );
  await new Promise<void>((ready, fail) => {
    createInterface({ input: child.stdout! }).once('line', () => ready());
    child.once('exit', (code) => fail(new Error(`fake ollama exited (${code})`)));
  });
  return child;
}

let app: ElectronApplication;
let page: Page;
let fake: ChildProcess;
let corePort: number;
let netLog: string;
let tmp: string;

/** A Core REST call made from the renderer with the session token, the way the UI makes it. */
function core<T>(method: string, path: string, body?: unknown): Promise<T> {
  return page.evaluate(
    async ({ method, path, body }) => {
      const config = await window.universe!.getConfig();
      const response = await fetch(`${config.coreUrl}/api/v1${path}`, {
        method,
        headers: { Authorization: `Bearer ${config.token}`, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok)
        throw new Error(`${method} ${path}: HTTP ${response.status} ${await response.text()}`);
      return (await response.json()) as T;
    },
    { method, path, body },
  );
}

async function queueDrained(): Promise<void> {
  await expect
    .poll(
      async () => {
        const stats = await core<{ queued: number; leased: number }>('GET', '/jobs/stats');
        return stats.queued + stats.leased;
      },
      { timeout: 90_000, intervals: [250, 500, 1000] },
    )
    .toBe(0);
}

async function windowWithHash(hash: string): Promise<Page> {
  await expect.poll(() => app.windows().some((w) => w.url().endsWith(hash)), { timeout: 30_000 }).toBe(true);
  return app.windows().find((w) => w.url().endsWith(hash))!;
}

test.beforeAll(async () => {
  tmp = mkdtempSync(join(tmpdir(), 'universe-e2e-'));
  netLog = join(tmp, 'netlog.json');
  const ollamaPort = await freePort();
  corePort = await freePort();
  fake = await startFakeOllama(ollamaPort);
  app = await electron.launch({
    executablePath: electronPath,
    // CI runners have no GPU: allow Chromium's software WebGL so the 3D scene is exercised too.
    args: [
      ...(process.platform === 'linux' ? ['--no-sandbox'] : []),
      '--enable-unsafe-swiftshader',
      `--log-net-log=${netLog}`, // every request the app makes, checked by the last test
      join(root, 'apps', 'desktop'),
    ],
    cwd: root,
    env: {
      ...process.env,
      UNIVERSE_DATA_DIR: join(tmp, 'data'),
      UNIVERSE_VAULT_DIR: join(tmp, 'vault'),
      UNIVERSE_USER_DATA_DIR: join(tmp, 'profile'),
      UNIVERSE_CORE_PORT: String(corePort),
      UNIVERSE_OLLAMA_URL: `http://127.0.0.1:${ollamaPort}`,
      UNIVERSE_MANAGE_OLLAMA: '0',
      UNIVERSE_UI_URL: '', // use the built UI over app://
    },
  });
  page = await app.firstWindow();
  // The command bar window is created hidden at startup: make sure `page` is the main window.
  await expect
    .poll(() => app.windows().some((w) => !w.url().endsWith('#command-bar')), { timeout: 30_000 })
    .toBe(true);
  page = app.windows().find((w) => !w.url().endsWith('#command-bar'))!;
});

test.afterAll(async () => {
  await app?.close().catch(() => {});
  fake?.kill();
});

test('boots to a live HUD with the seed galaxies', async () => {
  await expect(page.getByTestId('core-status')).toHaveText(/Core online/, { timeout: 60_000 });
  await expect(page.getByTestId('agent-core')).toContainText('Core');
  const galaxies = page.getByTestId('galaxy-list');
  for (const name of ['Ember Wolf Acquisitions', 'DevMind', 'Algo trading bot', 'UNIVERSE']) {
    await expect(galaxies).toContainText(name);
  }
  // The WebGL universe rendered: the 3D scene, or Lite (a 2D WebGL graph), which Auto picks under software
  // rendering like this CI runner's.
  await expect(
    page.locator('[data-testid="universe-canvas"] canvas, [data-testid="lite-view"] canvas.sigma-nodes'),
  ).toBeVisible();
  await page.waitForTimeout(1500); // let the scene settle for the screenshot
  await page.screenshot({ path: 'test-results/hud.png' });
});

test('chat streams a reply from the local model', async () => {
  await page.getByTestId('orb').click();
  const input = page.getByLabel('Message Core');
  await input.fill('hello universe');
  await input.press('Enter');
  const reply = page.getByTestId('assistant-message').last();
  await expect(reply).toContainText('Echo from the fake model: hello universe');
  await expect(reply).toHaveAttribute('data-status', 'complete');
  await page.screenshot({ path: 'test-results/chat.png' });
});

test('killing Core triggers an automatic restart and the app recovers', async () => {
  await page.keyboard.press('Control+k');
  await page.getByPlaceholder('Type a command…').last().fill('Simulate a Core crash');
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('core-status')).toHaveText(/Reconnecting|Connecting/, { timeout: 10_000 });
  await expect(page.getByTestId('core-status')).toHaveText(/Core online/, { timeout: 60_000 });
  await expect(page.getByTestId('activity')).toContainText('Core restarted after a crash');

  const input = page.getByLabel('Message Core');
  await input.fill('still there?');
  await input.press('Enter');
  await expect(page.getByTestId('assistant-message').last()).toContainText(
    'Echo from the fake model: still there?',
  );
});

test('the system panel shows vitals, services and hardware', async () => {
  await page.getByRole('tab', { name: 'System' }).click();
  await expect(page.getByTestId('vitals')).toContainText('pid');
  await expect(page.getByTestId('services')).toContainText(/core/i);
  await expect(page.getByTestId('hardware')).toContainText('RAM');
  await page.screenshot({ path: 'test-results/system.png' });
});

test('files added to the vault are found by keyword and by meaning', async () => {
  const source = join(tmp, 'my-files');
  mkdirSync(source);
  writeFileSync(
    join(source, 'quarterly-report.md'),
    '# Quarterly report\n\nRevenue grew in the northern region. A pricing review is planned.\n',
  );
  writeFileSync(join(source, 'river-walk.txt'), 'My puppy loves walking along the river every morning.\n');
  writeFileSync(join(source, 'shopping.txt'), 'eggs, flour, sugar, butter\n');

  // Drag-drop hands Core these same absolute paths (Electron's webUtils); Core copies the files in.
  const result = await core<{ queued: number }>('POST', '/ingest/paths', { paths: [source] });
  expect(result.queued).toBe(1); // one import job for the folder
  await page.getByTestId('view-list').click();
  await expect(page.getByTestId('items-count')).toHaveText('3 items', { timeout: 60_000 });
  await queueDrained(); // extracted, chunked and embedded by the worker process

  const search = page.getByTestId('search-input');
  await search.fill('northern region');
  await expect(page.getByTestId('item-row').first()).toContainText('Quarterly report');
  await expect(page.getByTestId('item-row').first()).toContainText('northern'); // the highlighted snippet

  // No word in common with the note: only the embedding (dog ≈ puppy, water ≈ river) can find it.
  await search.fill('dog near water');
  await expect(page.getByTestId('item-row').first()).toContainText('river-walk');
  await page.getByTestId('item-row').first().click();
  await expect(page.getByTestId('item-title')).toHaveText('river-walk');
  await expect(page.getByTestId('item-text')).toContainText('My puppy loves walking');
  await expect(page.getByTestId('item-stages')).toContainText('done');
  await page.screenshot({ path: 'test-results/vault-search.png' });

  await search.fill('');
  await page.getByTestId('view-grid').click();
  await expect(page.getByTestId('item-card')).toHaveCount(3);
  await page.screenshot({ path: 'test-results/vault-grid.png' });
});

test('the command bar finds items and captures notes', async () => {
  const bar = await windowWithHash('#command-bar');
  await page.evaluate(() => window.universe!.showCommandBar('search'));
  await expect(bar.getByTestId('bar-input')).toBeFocused();
  await bar.getByTestId('bar-input').fill('quarterly');
  await expect(bar.getByTestId('bar-hit').first()).toContainText('Quarterly report');
  await expect(bar.getByTestId('bar-capture-row')).toContainText('Save “quarterly” as a note');
  await bar.screenshot({ path: 'test-results/command-bar.png' });

  // Ctrl+Enter shows the item in the main window instead of opening it.
  await bar.getByTestId('bar-input').press('Control+Enter');
  await expect(page.getByTestId('item-title')).toHaveText('Quarterly report');

  // Quick capture: Tab switches modes, Ctrl+Enter saves, #hashtags become tags.
  await page.evaluate(() => window.universe!.showCommandBar('capture'));
  await expect(bar.getByTestId('bar-note')).toBeFocused();
  await bar.getByTestId('bar-note').fill('Call the accountant about the invoice #finance');
  await bar.getByTestId('bar-note').press('Control+Enter');
  await expect(bar.getByTestId('bar-status')).toHaveText('Saved to your inbox');

  await page.getByTestId('view-list').click();
  await page.getByTestId('search-input').fill('accountant');
  await expect(page.getByTestId('item-row').first()).toContainText('Call the accountant');
  await page.getByTestId('item-row').first().click();
  await expect(page.getByTestId('item-panel')).toContainText('#finance');
});

test('the vault panel shows counts and the background queue', async () => {
  await page.getByRole('tab', { name: 'Vault' }).click();
  await expect(page.getByTestId('vault-counts')).toContainText('4 items');
  await expect(page.getByTestId('queue')).toBeVisible();
  await expect(page.getByTestId('watched-folders')).toBeVisible();
  await page.screenshot({ path: 'test-results/vault-panel.png' });
});

test('the list scrolls smoothly through hundreds of items', async () => {
  await page.evaluate(async () => {
    const config = await window.universe!.getConfig();
    for (let i = 0; i < 300; i++) {
      await fetch(`${config.coreUrl}/api/v1/capture`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${config.token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: `Harbor log entry ${i}` }),
      });
    }
  });
  await queueDrained();
  await page.getByTestId('search-input').fill('');
  await page.getByTestId('view-list').click();
  await expect(page.getByTestId('items-count')).toHaveText('304 items'); // the total, not the loaded page

  // Scroll one step per frame from top to bottom and record how long each frame took.
  const gaps = await page.evaluate(async () => {
    const list = document.querySelector<HTMLElement>('[data-testid="items-list"]')!;
    const out: number[] = [];
    let last = performance.now();
    await new Promise<void>((done) => {
      const tick = (now: number) => {
        out.push(now - last);
        last = now;
        list.scrollTop += 60;
        const atEnd = list.scrollTop + list.clientHeight >= list.scrollHeight - 1;
        if ((atEnd && out.length > 30) || out.length > 400) done();
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    return out.slice(2);
  });
  const sorted = [...gaps].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)]!;
  const p95 = sorted[Math.floor(sorted.length * 0.95)]!;
  console.log(`list scroll: ${gaps.length} frames, median ${median.toFixed(1)} ms, p95 ${p95.toFixed(1)} ms`);
  // Every page loaded while scrolling, without jumping back to the top.
  await expect(page.getByTestId('item-row').last()).toBeVisible();
  // Software rendering in CI: hold 30 fps at the median (the 3D scene must not render behind the list).
  expect(median).toBeLessThan(34);
});

interface EngineStatus {
  available: boolean;
  reason: string | null;
  killswitch_engaged: boolean;
}

test('the agent dock, agents and safety panels show the engine', async () => {
  for (const id of ['core', 'navigator', 'librarian', 'scribe', 'critic']) {
    await expect(page.getByTestId(`agent-${id}`)).toBeVisible();
  }
  const engine = await core<EngineStatus>('GET', '/engine');
  await page.getByRole('tab', { name: 'Agents' }).click();
  await expect(page.getByTestId('agents-panel')).toBeVisible();
  if (engine.available) {
    await expect(page.getByTestId('engine-unavailable')).toHaveCount(0);
    await expect(page.getByTestId('killswitch')).toBeVisible();
  } else {
    await expect(page.getByTestId('engine-unavailable')).toContainText('chat without tools');
    await expect(page.getByTestId('run-agent')).toBeDisabled();
    await expect(page.getByTestId('killswitch')).toHaveCount(0);
  }
  await page.getByRole('tab', { name: 'Safety' }).click();
  await page.getByTestId('audit').getByRole('button', { name: 'Verify' }).click();
  await expect(page.getByTestId('audit')).toContainText('Intact');
  await page.screenshot({ path: 'test-results/safety.png' });
});

test('the agent roster shows synopses and stats, and agents can be added, turned off and removed', async () => {
  await page.getByRole('tab', { name: 'Agents' }).click();
  await page.getByTestId('agents-view-roster').click();
  const roster = page.getByTestId('agent-roster');
  for (const id of ['core', 'navigator', 'librarian', 'scribe', 'critic']) {
    const card = roster.locator(`[data-agent="${id}"]`);
    await expect(card.getByTestId('roster-synopsis')).not.toHaveText('No synopsis yet.');
    await expect(card.getByTestId('roster-stats')).toBeVisible();
  }
  await expect(roster.locator('[data-agent="core"]').getByTestId('roster-toggle')).toBeDisabled();

  // Add one: it shows in the roster and in the dock.
  await page.getByTestId('add-agent').click();
  await page.getByTestId('add-agent-name').fill('Deal Scout');
  await page.getByTestId('add-agent-purpose').fill('Finds land-deal notes and lists open questions.');
  await page
    .getByTestId('add-agent-synopsis')
    .fill('Reads your land-deal notes and says what is unanswered.');
  await page
    .getByTestId('add-agent-instructions')
    .fill('List the open questions in the land-deal notes, citing each.');
  await page.getByTestId('add-agent-save').click();
  const scout = roster.locator('[data-agent="deal-scout"]');
  await expect(scout.getByTestId('roster-synopsis')).toHaveText(/what is unanswered/);
  await expect(page.getByTestId('agent-deal-scout')).toBeVisible();

  // Turn a built-in off (it leaves the dock) and back on; edit a synopsis; remove yours.
  const librarian = roster.locator('[data-agent="librarian"]');
  await librarian.getByTestId('roster-toggle').click();
  await expect(librarian.getByTestId('roster-state')).toHaveText('off');
  await expect(page.getByTestId('agent-librarian')).toHaveCount(0);
  await librarian.getByTestId('roster-toggle').click();
  await expect(page.getByTestId('agent-librarian')).toBeVisible();
  await scout.getByRole('button', { name: /Edit Deal Scout/ }).click();
  await scout.getByTestId('roster-synopsis-editor').fill('Land questions, nothing else.');
  await scout.getByTestId('roster-synopsis-save').click();
  await expect(scout.getByTestId('roster-synopsis')).toHaveText('Land questions, nothing else.');
  page.once('dialog', (d) => void d.accept());
  await scout.getByTestId('roster-remove').click();
  await expect(scout).toHaveCount(0);
  await expect(page.getByTestId('agent-deal-scout')).toHaveCount(0);
  await page.screenshot({ path: 'test-results/agent-roster.png' });
  await page.getByTestId('agents-view-tasks').click();
});

test('done when: find notes, summarize them and link them to a galaxy, with an approval and an audit trail', async () => {
  const engine = await core<EngineStatus>('GET', '/engine');
  test.skip(!engine.available, `needs the Phase 3 protected-core patch: ${engine.reason}`);
  for (const [title, text] of [
    ['Austin land deal', 'The Austin land deal closes in November.'],
    ['Lake parcel land deal', 'A land deal by the lake: the owner is motivated.'],
  ]) {
    await core('POST', '/capture', { title, text });
  }
  await queueDrained();

  await page.getByRole('tab', { name: 'Agents' }).click();
  await page
    .getByTestId('agent-instruction')
    .fill('Find my notes about land deal, summarize them, and link them to project DevMind.');
  await page.getByTestId('run-agent').click();
  // Reading your notes tainted the task, so linking them asks you first.
  const approval = page.getByTestId('approval');
  await expect(approval).toContainText("Add 2 item(s) to the galaxy 'DevMind'", { timeout: 30_000 });
  await page.screenshot({ path: 'test-results/approval.png' });
  await approval.getByTestId('approve').click();
  await expect(page.getByTestId('task-status')).toHaveText('done', { timeout: 30_000 });
  const output = page.getByTestId('task-output');
  await expect(output).toContainText('The Austin land deal closes in November.');
  await expect(output).toContainText('Added 2 item(s) to DevMind.');
  await expect(output).toContainText('Checked by Critic.');
  await expect(page.getByTestId('task-steps')).toContainText('project.add_items · asked you');
  await page.screenshot({ path: 'test-results/task-trace.png' });

  const linked = await core<{ items: { title: string }[] }>(
    'GET',
    `/items?project=${(await core<{ id: string; name: string }[]>('GET', '/projects')).find((p) => p.name === 'DevMind')!.id}`,
  );
  expect(linked.items.map((i) => i.title).sort()).toEqual(['Austin land deal', 'Lake parcel land deal']);

  await page.getByRole('tab', { name: 'Safety' }).click();
  const audit = page.getByTestId('audit');
  await audit.getByRole('button', { name: 'Verify' }).click();
  await expect(audit).toContainText('Intact');
  for (const action of ['task.started', 'tool.call · project.add_items', 'approval.decided', 'item.linked']) {
    await expect(audit).toContainText(action);
  }
});

test('the kill switch stops agents and only a native dialog releases it', async () => {
  const engine = await core<EngineStatus>('GET', '/engine');
  test.skip(!engine.available, `needs the Phase 3 protected-core patch: ${engine.reason}`);
  await page.getByTestId('killswitch').click();
  await expect(page.getByTestId('killswitch-banner')).toBeVisible();
  await expect.poll(async () => (await core<EngineStatus>('GET', '/engine')).killswitch_engaged).toBe(true);
  // Core's own API can't release it.
  await expect(core('POST', '/killswitch', { engaged: false })).rejects.toThrow('HTTP 403');
  // Answer the native dialog the way you would: "Release".
  await app.evaluate(({ dialog }) => {
    dialog.showMessageBox = (async () => ({
      response: 1,
      checkboxChecked: false,
    })) as typeof dialog.showMessageBox;
  });
  await page.getByTestId('killswitch-banner').getByRole('button', { name: 'Release…' }).click();
  await expect(page.getByTestId('killswitch-banner')).toHaveCount(0);
  await expect.poll(async () => (await core<EngineStatus>('GET', '/engine')).killswitch_engaged).toBe(false);
});

test('nothing leaves the machine: no requests to non-loopback hosts', async () => {
  await app.close(); // flushes the net log
  expect(existsSync(netLog)).toBe(true);
  const urls = readFileSync(netLog, 'utf8').match(/"(?:https?|wss?):\/\/[^"/\\]+/g) ?? [];
  const external = [...new Set(urls.map((u) => u.slice(1)))].filter(
    (u) => !/^(https?|wss?):\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(u),
  );
  expect(external).toEqual([]);
});
