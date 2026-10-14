import { describe, expect, it, vi } from 'vitest';
import { KillSwitchControl, parseKillSwitchFile } from './killswitch';

function control(overrides: Partial<ConstructorParameters<typeof KillSwitchControl>[0]> = {}) {
  const calls: string[] = [];
  const ks = new KillSwitchControl({
    initial: false,
    setOnSupervisor: vi.fn(async (engaged: boolean) => {
      calls.push(`supervisor:${engaged}`);
      return { engaged, core_acked: true };
    }),
    stopCapture: () => calls.push('capture-stopped'),
    confirmRelease: async () => true,
    onChange: (engaged) => calls.push(`changed:${engaged}`),
    log: () => {},
    ...overrides,
  });
  return { ks, calls };
}

describe('kill switch', () => {
  it('stops capture locally before anything else, and shows engaged at once', async () => {
    const { ks, calls } = control();
    await ks.set(true, 'hotkey');
    expect(calls).toEqual(['capture-stopped', 'changed:true', 'supervisor:true']);
    expect(ks.engaged).toBe(true);
  });

  it('releases only after the native dialog is confirmed', async () => {
    const declined = control({ initial: true, confirmRelease: async () => false });
    await declined.ks.set(false, 'hud');
    expect(declined.ks.engaged).toBe(true);
    expect(declined.calls).toEqual([]);

    const confirmed = control({ initial: true });
    await confirmed.ks.set(false, 'tray');
    expect(confirmed.ks.engaged).toBe(false);
    expect(confirmed.calls).toEqual(['supervisor:false', 'changed:false']);
  });

  it('reads the state file fail-safe', () => {
    expect(parseKillSwitchFile(null)).toBe(false); // no file: never engaged
    expect(parseKillSwitchFile('{"engaged":true}')).toBe(true);
    expect(parseKillSwitchFile('{"engaged":false}')).toBe(false);
    expect(parseKillSwitchFile('{garbage')).toBe(true); // unreadable: engaged
  });
});
