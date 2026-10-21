// Microphone consent (SPEC §3.4 and §11, ARCHITECTURE.md §1.3). PROTECTED CORE.
// The mic is off at every launch. Only this code turns it on, and only after you confirm a native dialog (once
// per launch), which no renderer code can click. Turning it off is instant, from anywhere. Chromium is only
// allowed to open an audio-only stream for our own main window while consent is on; the kill switch revokes it
// before anything else.

export interface ConsentState {
  available: true;
  mic: boolean;
  reason: string | null;
}

export type ConsentVia = 'hud' | 'voice' | 'tray' | 'killswitch' | 'window';

export interface MediaRequest {
  permission: string;
  /** For a permission request: the media types asked for. For a check: the one being checked. */
  mediaTypes: readonly string[];
  requestingUrl: string;
  fromMainWindow: boolean;
}

/** Whether Chromium may hand out a stream: audio only, our own UI, our main window, consent on. */
export function mediaAllowed(req: MediaRequest, mic: boolean, appOrigins: readonly string[]): boolean {
  if (req.permission !== 'media' || !mic || !req.fromMainWindow) return false;
  if (req.mediaTypes.length === 0 || req.mediaTypes.some((t) => t !== 'audio')) return false;
  let origin: string;
  try {
    const url = new URL(req.requestingUrl);
    origin = `${url.protocol}//${url.host}`; // URL.origin is "null" for custom schemes like app://
  } catch {
    return false;
  }
  return appOrigins.includes(origin);
}

export class MicConsent {
  mic = false; // off at every launch, whatever it was last time
  private confirmed = false;

  constructor(
    private readonly opts: {
      /** A native yes/no dialog; resolves true only if you confirm. */
      confirm: () => Promise<boolean>;
      killSwitchEngaged: () => boolean;
      onChange: (state: ConsentState) => void;
      /** The audit trail (Core's consent record); failures are logged, never block turning the mic off. */
      record: (mic: boolean, via: ConsentVia) => Promise<void>;
      log: (event: string, fields: Record<string, unknown>) => void;
    },
  ) {}

  state(reason: string | null = null): ConsentState {
    return { available: true, mic: this.mic, reason };
  }

  async request(on: boolean, via: ConsentVia): Promise<ConsentState> {
    if (!on) {
      this.set(false, via);
      return this.state();
    }
    if (this.opts.killSwitchEngaged())
      return this.state('The kill switch is engaged: the microphone stays off.');
    if (this.mic) return this.state();
    if (!this.confirmed) {
      if (!(await this.opts.confirm())) return this.state('You kept the microphone off.');
      if (this.opts.killSwitchEngaged())
        return this.state('The kill switch is engaged: the microphone stays off.');
      this.confirmed = true;
    }
    this.set(true, via);
    return this.state();
  }

  /** The kill switch, a closed window, or the tray: off now, no questions. */
  revoke(via: ConsentVia): boolean {
    const was = this.mic;
    this.set(false, via);
    return was;
  }

  private set(mic: boolean, via: ConsentVia): void {
    if (mic === this.mic) return;
    this.mic = mic;
    this.opts.log('consent_changed', { kind: 'mic', on: mic, via });
    this.opts.onChange(this.state());
    this.opts
      .record(mic, via)
      .catch((err: unknown) =>
        this.opts.log('consent_record_failed', { error: err instanceof Error ? err.message : String(err) }),
      );
  }
}
