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
