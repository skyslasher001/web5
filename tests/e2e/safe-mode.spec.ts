// Safe mode end to end: Core can't start (its port is taken), the supervisor enters safe mode,
// Core fails there too, and Electron shows the static safe-mode page. Freeing the port and
// choosing "Try a normal start" brings the app back.
import { _electron as electron, expect, test, type ElectronApplication } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { createServer, type Server } from 'node:net';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..');
const electronPath = createRequire(join(root, 'apps', 'desktop', 'package.json'))(
  'electron',
) as unknown as string;

function occupyPort(): Promise<{ server: Server; port: number; release: () => Promise<void> }> {
  return new Promise((ok, fail) => {
    const sockets = new Set<import('node:net').Socket>();
    const server = createServer((socket) => {
      sockets.add(socket);
      socket.on('close', () => sockets.delete(socket));
    });
    const release = () =>
      new Promise<void>((done) => {
        for (const socket of sockets) socket.destroy(); // health checks keep connections open
        server.close(() => done());
      });
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (typeof address === 'object' && address) ok({ server, port: address.port, release });
      else fail(new Error('no port'));
    });
  });
}

let app: ElectronApplication;

test.afterAll(async () => {
  await app?.close().catch(() => {});
});

test('a Core that cannot start leads to the safe-mode page, and recovery works', async () => {
  const tmp = mkdtempSync(join(tmpdir(), 'universe-safe-'));
  const { port, release } = await occupyPort();
  app = await electron.launch({
    executablePath: electronPath,
    args: [...(process.platform === 'linux' ? ['--no-sandbox'] : []), join(root, 'apps', 'desktop')],
    cwd: root,
    env: {
      ...process.env,
      UNIVERSE_DATA_DIR: join(tmp, 'data'),
      UNIVERSE_VAULT_DIR: join(tmp, 'vault'),
      UNIVERSE_USER_DATA_DIR: join(tmp, 'profile'),
      UNIVERSE_CORE_PORT: String(port),
      UNIVERSE_OLLAMA_URL: 'http://127.0.0.1:9',
      UNIVERSE_MANAGE_OLLAMA: '0',
      UNIVERSE_BOOT_TIMEOUT_S: '10',
      UNIVERSE_UI_URL: '',
    },
  });
  const page = await app.firstWindow();
  await expect(page.getByRole('heading', { name: "UNIVERSE couldn't start normally" })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.locator('#reason')).toContainText('failed to start 2 times');
  await expect(page.locator('#core-state')).toContainText('failed');
  await expect(page.locator('#log')).toContainText(/address already in use|only one usage/i); // the real cause
  await page.screenshot({ path: 'test-results/safe-mode.png' });

  await release();
  await page.getByRole('button', { name: 'Try a normal start' }).click();
  await expect(page.getByRole('button', { name: 'Back to UNIVERSE' })).toBeEnabled({ timeout: 60_000 });
  await page.getByRole('button', { name: 'Back to UNIVERSE' }).click();
  await expect(page.getByTestId('core-status')).toHaveText(/Core online/, { timeout: 60_000 });
});
