// JSON-lines logger for the main process (logs/desktop.jsonl).
import { appendFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

export interface Logger {
  info(event: string, fields?: Record<string, unknown>): void;
  warn(event: string, fields?: Record<string, unknown>): void;
  error(event: string, fields?: Record<string, unknown>): void;
}

export function createLogger(file: string, secrets: string[] = []): Logger {
  mkdirSync(dirname(file), { recursive: true });
  const scrub = (text: string) =>
    secrets.reduce((acc, s) => (s ? acc.split(s).join('[redacted]') : acc), text);
  const write = (level: string, event: string, fields: Record<string, unknown> = {}) => {
    const line = scrub(
      JSON.stringify({ timestamp: new Date().toISOString(), level, logger: 'desktop', event, ...fields }),
    );
    try {
      appendFileSync(file, line + '\n');
    } catch {
      // logging must never crash the app
    }
    if (level !== 'info') console.error(line);
  };
  return {
    info: (e, f) => write('info', e, f),
    warn: (e, f) => write('warning', e, f),
    error: (e, f) => write('error', e, f),
  };
}
