import { defineConfig } from '@playwright/test';

// Drives the real Electron app (built UI, real supervisor and Core, fake Ollama). Run `pnpm build` first.
export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 120_000,
  expect: { timeout: 30_000 },
  workers: 1,
  retries: 0,
  reporter: [['list']],
  outputDir: 'test-results',
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
});
