import { RotateCw, ShieldAlert } from 'lucide-react';
import { useState } from 'react';
import { bridge } from '../lib/bridge';
import { useUniverse } from '../state/store';

export function ConnectionBanner() {
  const connection = useUniverse((s) => s.connection);
  const attempt = useUniverse((s) => s.reconnectAttempt);
  const supervisor = useUniverse((s) => s.desktop?.supervisor);
  const process = useUniverse((s) => s.desktop?.process);
  const [busy, setBusy] = useState(false);
  const core = supervisor?.services.core;

  if (supervisor?.safe_mode.active) {
    return (
      <div
        role="alert"
        className="pointer-events-auto absolute top-14 left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-full border border-danger/40 bg-space-1/90 px-4 py-2 text-sm"
      >
        <ShieldAlert className="size-4 text-danger" aria-hidden />
        <span>
          Safe mode: agents are disabled.{' '}
          {supervisor.safe_mode.running_from === 'lkg' ? 'Running the last-known-good version.' : ''}
        </span>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void bridge()
              .exitSafeMode()
              .finally(() => setBusy(false));
          }}
          className="rounded-full border border-hairline-2 px-3 py-0.5 text-xs hover:border-accent disabled:opacity-50"
        >
          Try a normal start
        </button>
      </div>
    );
  }
  if (connection === 'online') return null;
  const detail =
    process && process !== 'running'
      ? `Supervisor ${process}`
      : core
        ? `Core ${core.state}${core.restarts ? ` · restart ${core.restarts}` : ''}`
        : 'Waiting for the supervisor';
  return (
    <div
      role="status"
      data-testid="connection-banner"
      className="pointer-events-auto absolute top-14 left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-full border border-amber/40 bg-space-1/90 px-4 py-2 text-sm"
    >
      <RotateCw className="size-4 orb-spin text-amber" aria-hidden />
      <span>
        {connection === 'connecting' ? 'Connecting to Core…' : `Reconnecting to Core (attempt ${attempt})…`}
      </span>
      <span className="font-mono text-xs text-ink-3">{detail}</span>
    </div>
  );
}
