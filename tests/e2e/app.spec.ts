// Phase 1 "done when": launch the app, chat with streaming replies, kill the backend and watch it
// auto-restart. Uses the real Electron app, supervisor and Core; only the model server is a stand-in.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
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
    {
      cwd: root,
      stdio: ['ignore', 'pipe', 'inherit'],
      shell: process.platform === 'win32',
    },
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

test.beforeAll(async () => {
  const tmp = mkdtempSync(join(tmpdir(), 'universe-e2e-'));
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
  await expect(page.locator('canvas')).toBeVisible(); // the WebGL universe rendered
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

test('nothing leaves the machine: no requests to non-loopback hosts', async () => {
  await app.close(); // flushes the net log
  expect(existsSync(netLog)).toBe(true);
  const urls = readFileSync(netLog, 'utf8').match(/"(?:https?|wss?):\/\/[^"/\\]+/g) ?? [];
  const external = [...new Set(urls.map((u) => u.slice(1)))].filter(
    (u) => !/^(https?|wss?):\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(u),
  );
  expect(external).toEqual([]);
});
