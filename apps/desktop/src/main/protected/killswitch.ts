// The global kill switch (SPEC §15, ARCHITECTURE.md §1.4). PROTECTED CORE.
// Engaging is instant and needs no confirmation: capture stops here first, then the supervisor stops the
// agents and network jobs (restarting Core if it doesn't answer). Releasing needs a native dialog, which
// no renderer code (and nothing in Core) can click.
import { readFileSync } from 'node:fs';

export const KILL_SWITCH_HOTKEY = 'CommandOrControl+Alt+Shift+K';

export interface KillSwitchResult {
  engaged: boolean;
  core_acked: boolean;
}

/** The state file the supervisor writes; unreadable means engaged (fail safe), missing means off. */
export function parseKillSwitchFile(text: string | null): boolean {
  if (text === null) return false;
  try {
    const value = JSON.parse(text) as { engaged?: unknown };
    return value.engaged === true;
  } catch {
    return true;
  }
}

export function readKillSwitchFile(path: string): boolean {
  let text: string | null = null;
  try {
    text = readFileSync(path, 'utf8');
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== 'ENOENT') return true;
  }
  return parseKillSwitchFile(text);
}

export class KillSwitchControl {
  engaged: boolean;

  constructor(
    private readonly opts: {
      initial: boolean;
      /** POST /killswitch on the supervisor. */
      setOnSupervisor: (engaged: boolean) => Promise<KillSwitchResult>;
      /** Stop mic, screen and camera capture locally, before anything else (none exists before Phase 7). */
      stopCapture: () => void;
      /** A native yes/no dialog; resolves true only if you confirm. */
      confirmRelease: () => Promise<boolean>;
      onChange: (engaged: boolean) => void;
      log: (event: string, fields: Record<string, unknown>) => void;
    },
  ) {
    this.engaged = opts.initial;
  }

  async set(engaged: boolean, via: string): Promise<KillSwitchResult> {
    if (engaged) {
      this.opts.stopCapture();
    } else if (!(await this.opts.confirmRelease())) {
      return { engaged: this.engaged, core_acked: true };
    }
    // Reflect an engage at once, even if the supervisor is slow: the indicator must never lag behind.
    if (engaged) this.update(true);
    const result = await this.opts.setOnSupervisor(engaged);
    this.update(result.engaged);
    this.opts.log('killswitch', { engaged: result.engaged, via, core_acked: result.core_acked });
    return result;
  }

  private update(engaged: boolean): void {
    if (engaged === this.engaged) return;
    this.engaged = engaged;
    this.opts.onChange(engaged);
  }
}
