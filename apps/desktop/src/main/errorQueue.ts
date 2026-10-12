// Error reports from Electron main and the renderer, held until Core accepts them.

export type ErrorReport = Record<string, unknown>;
/** Delivers one report and resolves with the HTTP status; rejects when Core isn't reachable. */
export type SendReport = (report: ErrorReport) => Promise<number>;

export function createErrorQueue(send: SendReport, onRejected: (status: number) => void, limit = 50) {
  const pending: ErrorReport[] = [];
  let flushing = false;

  async function flush(): Promise<void> {
    if (flushing) return; // one flusher at a time, or the head report is sent twice
    flushing = true;
    try {
      for (let head = pending[0]; head; head = pending[0]) {
        const status = await send(head);
        if (status >= 400 && status < 500) {
          // Rejected as invalid: retrying can't succeed, and it would block every report behind it.
          onRejected(status);
        } else if (status < 200 || status >= 300) {
          return; // Core is unhealthy; retried on the next flush
        }
        pending.shift();
      }
    } catch {
      // Core not reachable yet; retried on the next flush
    } finally {
      flushing = false;
    }
  }

  return {
    push(report: ErrorReport): void {
      if (pending.length < limit) pending.push(report);
    },
    flush,
    get size(): number {
      return pending.length;
    },
  };
}
