// JSON-lines logger for the main process (logs/desktop.jsonl), rotated at 5 MB like the other services.
import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from 'node:fs';
import { dirname } from 'node:path';

export interface Logger {
  info(event: string, fields?: Record<string, unknown>): void;
  warn(event: string, fields?: Record<string, unknown>): void;
  error(event: string, fields?: Record<string, unknown>): void;
}

export function createLogger(file: string, secrets: string[] = [], maxBytes = 5 * 1024 * 1024): Logger {
  mkdirSync(dirname(file), { recursive: true });
  let size = existsSync(file) ? statSync(file).size : 0;
  const scrub = (text: string) =>
    secrets.reduce((acc, s) => (s ? acc.split(s).join('[redacted]') : acc), text);
  const write = (level: string, event: string, fields: Record<string, unknown> = {}) => {
    const line = scrub(
      JSON.stringify({ timestamp: new Date().toISOString(), level, logger: 'desktop', event, ...fields }),
    );
    try {
      if (size > maxBytes) {
        renameSync(file, `${file}.1`); // keep one previous file, like the Python services
        size = 0;
      }
      appendFileSync(file, line + '\n');
      size += Buffer.byteLength(line) + 1;
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
