import { describe, expect, it, vi } from 'vitest';
import { MicConsent, mediaAllowed, type MediaRequest } from './consent';

function make(opts: { confirm?: boolean[]; killed?: boolean } = {}) {
  const answers = [...(opts.confirm ?? [true])];
  const killed = { value: opts.killed ?? false };
  const changes: boolean[] = [];
  const records: Array<[boolean, string]> = [];
  const confirm = vi.fn(async () => answers.shift() ?? false);
  const consent = new MicConsent({
    confirm,
    killSwitchEngaged: () => killed.value,
    onChange: (s) => changes.push(s.mic),
    record: async (mic, via) => {
      records.push([mic, via]);
    },
    log: () => {},
  });
  return { consent, confirm, changes, records, killed };
}

describe('MicConsent', () => {
  it('is off at launch and turns on only after the native dialog', async () => {
    const { consent, confirm, changes, records } = make({ confirm: [true] });
    expect(consent.mic).toBe(false);
    const state = await consent.request(true, 'hud');
    expect(state).toEqual({ available: true, mic: true, reason: null });
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(changes).toEqual([true]);
    expect(records).toEqual([[true, 'hud']]);
  });

  it('stays off when you decline, and asks again next time', async () => {
    const { consent, confirm } = make({ confirm: [false, true] });
    expect((await consent.request(true, 'hud')).mic).toBe(false);
    expect((await consent.request(true, 'hud')).mic).toBe(true);
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it('asks once per launch; turning off is instant and needs no dialog', async () => {
    const { consent, confirm, changes } = make({ confirm: [true] });
    await consent.request(true, 'hud');
    expect((await consent.request(false, 'voice')).mic).toBe(false);
    expect((await consent.request(true, 'hud')).mic).toBe(true);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(changes).toEqual([true, false, true]);
  });

  it('refuses while the kill switch is engaged, even after you confirmed', async () => {
    const { consent, confirm, killed } = make({ killed: true });
    const state = await consent.request(true, 'hud');
    expect(state.mic).toBe(false);
    expect(state.reason).toMatch(/kill switch/);
    expect(confirm).not.toHaveBeenCalled();
    // Engaged while the dialog was open: still off.
    killed.value = false;
    const pending = make({ confirm: [true] });
    pending.confirm.mockImplementationOnce(async () => {
      pending.killed.value = true;
      return true;
    });
    expect((await pending.consent.request(true, 'hud')).mic).toBe(false);
  });

  it('the kill switch revokes it at once', async () => {
    const { consent, records } = make();
    await consent.request(true, 'hud');
    expect(consent.revoke('killswitch')).toBe(true);
    expect(consent.mic).toBe(false);
    expect(consent.revoke('killswitch')).toBe(false); // already off: nothing to record
    expect(records).toEqual([
      [true, 'hud'],
      [false, 'killswitch'],
    ]);
  });

  it('a failing audit record never blocks turning the mic off', async () => {
    const log = vi.fn();
    const consent = new MicConsent({
      confirm: async () => true,
      killSwitchEngaged: () => false,
      onChange: () => {},
      record: async () => {
        throw new Error('Core is restarting');
      },
      log,
    });
    await consent.request(true, 'hud');
    expect((await consent.request(false, 'tray')).mic).toBe(false);
    await new Promise((r) => setTimeout(r, 0));
    expect(log).toHaveBeenCalledWith('consent_record_failed', { error: 'Core is restarting' });
  });
});

describe('mediaAllowed', () => {
  const ours = ['app://universe'];
  const audio: MediaRequest = {
    permission: 'media',
    mediaTypes: ['audio'],
    requestingUrl: 'app://universe/index.html',
    fromMainWindow: true,
  };

  it('allows an audio stream for our main window only while consent is on', () => {
    expect(mediaAllowed(audio, true, ours)).toBe(true);
    expect(mediaAllowed(audio, false, ours)).toBe(false);
  });

  it.each<[string, Partial<MediaRequest>]>([
    ['the camera', { mediaTypes: ['video'] }],
    ['audio and video', { mediaTypes: ['audio', 'video'] }],
    ['no media type', { mediaTypes: [] }],
    ['another window (the command bar)', { fromMainWindow: false }],
    ['a page that is not ours', { requestingUrl: 'https://example.com/' }],
    ['a garbled origin', { requestingUrl: 'not a url' }],
    ['another permission', { permission: 'notifications' }],
  ])('refuses %s', (_name, change) => {
    expect(mediaAllowed({ ...audio, ...change }, true, ours)).toBe(false);
  });

  it('allows the dev server origin when that is what the app loads', () => {
    const dev = { ...audio, requestingUrl: 'http://127.0.0.1:5173/' };
    expect(mediaAllowed(dev, true, ['app://universe', 'http://127.0.0.1:5173'])).toBe(true);
    expect(mediaAllowed(dev, true, ours)).toBe(false);
  });
});
