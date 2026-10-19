// Phase 1 "done when": launch the app, chat with streaming replies, kill the backend and watch it
// auto-restart. Phase 2: add files, find them by keyword and by meaning, use the command bar.
// Phase 3: "find my notes about X, summarize them, and link them to project Y" with an approval and a full
// audit trail (needs the protected-core patch; without it the panels say agents chat without tools).
// Uses the real Electron app, supervisor, Core and pipeline workers; only the model server is a stand-in.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
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
let forgeRepo: string;

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
  // Forge repairs a scratch repository with an injected bug, never this checkout (Phase 5).
  forgeRepo = execFileSync(
    'uv',
    [
      'run', '--quiet', 'python', '-c',
      'import sys; from pathlib import Path; from tests.support.forge_repo import make_repo; print(make_repo(Path(sys.argv[1])))',
      join(tmp, 'forge'),
    ],
    { cwd: root, encoding: 'utf8' },
  ).trim(); // prettier-ignore
  app = await electron.launch({
    executablePath: electronPath,
    // CI runners have no GPU: allow Chromium's software WebGL so the 3D scene is exercised too.
    args: [
      ...(process.platform === 'linux' ? ['--no-sandbox'] : []),
      '--enable-unsafe-swiftshader',
      '--use-fake-device-for-media-stream', // a fake mic, for when the consent patch lets one open (Phase 7)
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
      UNIVERSE_REPO_DIR: forgeRepo,
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
  // System Vitals: Core's heartbeat in one place (SPEC §20).
  const vitals = page.getByTestId('system-vitals');
  await expect(vitals.getByTestId('vital-services')).toHaveAttribute('data-level', 'good');
  await expect(vitals.getByTestId('vital-models')).toContainText(/in memory|fake-chat/);
  await expect(vitals.getByTestId('vital-queue')).not.toHaveAttribute('data-level', 'off');
  await expect(vitals.getByTestId('vital-backups')).toContainText('not set up');
  await expect(vitals.getByTestId('vital-forge')).not.toContainText('…');
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

test('done when (Phase 5): Forge fixes an injected bug, you approve it, it applies, and rollback works', async () => {
  const status = await core<{ agent: boolean; sentinel: boolean; available: boolean }>(
    'GET',
    '/forge/status',
  );
  expect(status.available).toBe(true); // the scratch repository
  await page.getByRole('tab', { name: 'Forge' }).click();
  await page.getByTestId('forge-report').fill('add(2, 3) returns -1 instead of 5');
  await page.getByTestId('forge-report-send').click();
  await expect(page.getByTestId('forge-issue').first()).toContainText('add(2, 3) returns -1');
  if (!status.agent || !status.sentinel) {
    // Without the Phase 5 protected-core patch the UI says what's missing and Forge can't start.
    await expect(page.getByTestId('forge-missing')).toContainText('protected core');
    await expect(page.getByTestId('forge-fix').first()).toBeDisabled();
    test.skip(true, 'the rest needs the Phase 5 protected-core patch (Forge agent, Sentinel, releases)');
  }
  await page.getByTestId('forge-fix').first().click();
  await page.getByRole('tab', { name: 'Forge' }).click(); // asking Forge shows its task; come back
  const card = page.getByTestId('proposal').first();
  await expect(card).toHaveAttribute('data-status', 'ready', { timeout: 180_000 });
  await expect(page.getByTestId('forge-card')).toBeVisible(); // it waits in the approvals tray too
  await card.locator('button').first().click();
  await expect(card.getByTestId('proposal-diff')).toContainText('+    return a + b');
  await expect(card.getByTestId('proposal-verification')).toContainText('fails on the old code');
  await expect(card.getByTestId('proposal-reviews')).toContainText('passed');
  await page.screenshot({ path: 'test-results/forge-proposal.png' });

  // Approve: the native dialog in Electron main asks; answer "Apply" the way you would.
  await app.evaluate(({ dialog }) => {
    dialog.showMessageBox = (async () => ({
      response: 1,
      checkboxChecked: false,
    })) as typeof dialog.showMessageBox;
  });
  await card.getByTestId('proposal-approve').click();
  const calc = join(forgeRepo, 'calc', '__init__.py');
  await expect.poll(() => readFileSync(calc, 'utf8'), { timeout: 60_000 }).toContain('return a + b');
  await expect(card).toHaveAttribute('data-status', 'applied', { timeout: 60_000 });

  // One-click rollback from the System panel (the native dialog asks again).
  await page.getByRole('tab', { name: 'System' }).click();
  await page.getByTestId('release-rollback').first().click();
  await expect.poll(() => readFileSync(calc, 'utf8'), { timeout: 60_000 }).toContain('return a - b');
  // Core restarts after the rollback; once it's back, Electron main records the rollback and the issue reopens.
  await page.getByRole('tab', { name: 'Forge' }).click();
  await expect(card).toHaveAttribute('data-status', 'rolled_back', { timeout: 60_000 });
  await expect(page.getByTestId('core-status')).toHaveText(/Core online/, { timeout: 60_000 });
});

type VoiceDebug = {
  state: string;
  reply: string | null;
  error: string | null;
  micOn: boolean;
  selectedProjectId: string | null;
  panel: string;
  view: string;
};
const voiceState = () =>
  page.evaluate(() =>
    (window as unknown as { __universeDebug: { voiceState(): VoiceDebug } }).__universeDebug.voiceState(),
  );
const heard = (text: string) =>
  page.evaluate(
    (t) =>
      (
        window as unknown as { __universeDebug: { voiceHeard(s: string): Promise<void> } }
      ).__universeDebug.voiceHeard(t),
    text,
  );

test('Phase 7: voice turns on, routes what you say, and the mic opens only with your consent', async () => {
  await page.getByRole('button', { name: 'Voice settings' }).click();
  const panel = page.getByTestId('voice-panel');
  await expect(panel).toBeVisible();
  await expect(page.getByTestId('voice-model-whisper-tiny.en')).toContainText('Install');
  // Turning voice on starts the real voice process (no models here: it neither hears nor speaks yet).
  await page.getByTestId('voice-start').click();
  await expect(panel).toContainText('On · no speech-to-text · no voice', { timeout: 60_000 });
  await expect(page.getByTestId('voice-orb')).toHaveAttribute('data-state', 'idle');

  // The mic belongs to protected main code (docs/proposals/phase-7-consent.md).
  const consent = await page.evaluate(() => window.universe!.getConsent());
  if (!consent.available) {
    // Without the patch it stays off and says why.
    await page.getByTestId('voice-mic').click();
    await expect(page.getByTestId('voice-consent')).toContainText('Phase 7 protected-core patch');
    await expect(page.getByTestId('mic-indicator')).toHaveCount(0);
    expect((await voiceState()).micOn).toBe(false);
  } else {
    // With it: off at launch; declining the native dialog keeps it off; confirming opens the (fake) mic.
    expect(consent.mic).toBe(false);
    const answer = async (response: number) =>
      app.evaluate(({ dialog }, r) => {
        dialog.showMessageBox = (async () => ({
          response: r,
          checkboxChecked: false,
        })) as typeof dialog.showMessageBox;
      }, response);
    await answer(0);
    await page.getByTestId('voice-mic').click();
    await expect(page.getByTestId('voice-consent')).toContainText('You kept the microphone off');
    expect((await voiceState()).micOn).toBe(false);
    await answer(1);
    await page.getByTestId('voice-mic').click();
    await expect(page.getByTestId('mic-indicator')).toContainText('Microphone on');
    await expect.poll(async () => (await voiceState()).micOn).toBe(true);
    await expect(page.getByTestId('voice-orb')).toHaveAttribute('data-state', /idle|listening/);
    const audit = await core<{ details: { on: boolean; via: string } }[]>(
      'GET',
      '/audit?action=consent.changed',
    );
    expect(audit[0]?.details).toEqual({ on: true, via: 'hud' });
    // Left on: the kill switch test below checks that it turns the mic off.
  }

  // What Whisper would hand over: commands run here, navigation takes the recall fast path, questions go to Core.
  await heard('Open the agents panel.');
  expect((await voiceState()).panel).toBe('agents');
  await heard('Show the grid view.');
  expect((await voiceState()).view).toBe('grid');
  await heard('Universe view');
  const projects = await core<{ id: string; name: string }[]>('GET', '/projects');
  await heard('Take me to Ember Wolf.');
  await expect
    .poll(async () => (await voiceState()).selectedProjectId)
    .toBe(projects.find((p) => p.name === 'Ember Wolf Acquisitions')!.id);
  await expect(page.getByTestId('voice-bubble')).toContainText('Flying to Ember Wolf Acquisitions');
  await heard('What can you do?');
  await expect.poll(async () => (await voiceState()).reply ?? '', { timeout: 30_000 }).not.toBe('');
  await page.screenshot({ path: 'test-results/voice.png' });
});

test('the kill switch stops agents and only a native dialog releases it', async () => {
  const engine = await core<EngineStatus>('GET', '/engine');
  test.skip(!engine.available, `needs the Phase 3 protected-core patch: ${engine.reason}`);
  const micWasOn = (await page.evaluate(() => window.universe!.getConsent())).mic;
  await page.getByTestId('killswitch').click();
  await expect(page.getByTestId('killswitch-banner')).toBeVisible();
  if (micWasOn) {
    // Capture stops first, in main: consent revoked, the page holding the stream reloaded, the indicator gone.
    expect((await page.evaluate(() => window.universe!.getConsent())).mic).toBe(false);
    await expect(page.getByTestId('mic-indicator')).toHaveCount(0);
    const audit = await core<{ details: { on: boolean; via: string } }[]>(
      'GET',
      '/audit?action=consent.changed',
    );
    expect(audit[0]?.details).toEqual({ on: false, via: 'killswitch' });
  }
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
