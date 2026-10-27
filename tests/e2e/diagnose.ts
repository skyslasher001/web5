// When an e2e test fails, print what the app showed and what its services logged, so a CI job log is enough to
// see why (the uploaded artifacts can't always be fetched). Added after CI's first Windows run, 2026-10-27.
import type { Page, TestInfo } from '@playwright/test';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const MAX_SNAPSHOT = 6000;
const LOG_LINES = 60;

export async function reportFailure(info: TestInfo, page: Page | undefined, dataDir: string): Promise<void> {
  if (info.status === info.expectedStatus) return;
  await printDiagnostics(info.title, page, dataDir);
}

/** The same report for a failure outside a test (a beforeAll that waits for Core, say). */
export async function printDiagnostics(
  title: string,
  page: Page | undefined,
  dataDir: string,
): Promise<void> {
  const out: string[] = [`\n===== diagnostics: ${title} =====`];
  try {
    const snapshot = page ? await page.locator('body').ariaSnapshot({ timeout: 5_000 }) : '(no page)';
    out.push('--- page (accessibility snapshot) ---', snapshot.slice(0, MAX_SNAPSHOT));
  } catch (err) {
    out.push(`--- page: unavailable (${String(err).split('\n')[0]}) ---`);
  }
  const logs = join(dataDir, 'logs');
  if (existsSync(logs)) {
    for (const name of readdirSync(logs).sort()) {
      try {
        // Routine model-server polling (httpx) drowns the events; warnings and errors are always kept.
        const all = readFileSync(join(logs, name), 'utf-8').trimEnd().split('\n');
        const lines = all.filter((l) => !l.includes('"logger": "httpx"'));
        const problems = lines.filter((l) => /"level": ?"(warning|error|critical)"/.test(l));
        const tail = lines.slice(-LOG_LINES);
        const earlier = problems.filter((l) => !tail.includes(l));
        out.push(
          `--- ${name} (${all.length} lines; ${earlier.length} earlier warnings/errors, then the last ${tail.length} without httpx) ---`,
          ...earlier,
          ...tail,
        );
      } catch {
        // a directory or a file being rotated: skip it
      }
    }
  }
  out.push('===== end diagnostics =====\n');
  console.log(out.join('\n'));
}
