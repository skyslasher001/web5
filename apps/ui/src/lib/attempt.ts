import { useUniverse } from '../state/store';

/**
 * Run a fire-and-forget action. A failure (Core or the supervisor unreachable, say) becomes a visible
 * line in the activity ribbon instead of an unhandled rejection that would be filed as a renderer bug.
 */
export function attempt(label: string, task: Promise<unknown>): void {
  task.catch((err: unknown) => {
    const reason = err instanceof Error ? err.message : String(err);
    useUniverse.getState().addNotice('bad', `${label} failed: ${reason}`);
  });
}

/**
 * Start `start` unless its previous run (tracked by `flag`, a ref) is still in flight: a double Ctrl+Enter
 * or a second click starts one task, not two. Returns the run's promise for the caller to report, or null.
 */
export function startOnce(
  flag: { current: boolean },
  start: () => Promise<unknown>,
): Promise<unknown> | null {
  if (flag.current) return null;
  flag.current = true;
  let run: Promise<unknown>;
  try {
    run = start();
  } catch (err) {
    run = Promise.reject(err instanceof Error ? err : new Error(String(err)));
  }
  return run.finally(() => {
    flag.current = false;
  });
}
