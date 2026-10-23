// The kill switch: one press stops every agent. Electron main owns it (protected core); releasing it takes a
// native dialog that nothing in the renderer can click, so this UI can only ask.
import { OctagonX } from 'lucide-react';
import { useKillSwitch } from '../lib/killSwitch';
import { Button } from './ui';

export function KillSwitchButton() {
  const { available, engaged, engage } = useKillSwitch();
  if (!available || engaged) return null;
  return (
    <button
      type="button"
      onClick={engage}
      title="Kill switch: stop every agent now (Ctrl+Alt+Shift+K)"
      aria-label="Engage the kill switch"
      data-testid="killswitch"
      className="text-ink-3 transition-colors duration-150 hover:text-danger"
    >
      <OctagonX className="size-4" aria-hidden />
    </button>
  );
}

export function KillSwitchBanner() {
  const { available, engaged, release } = useKillSwitch();
  if (!engaged) return null;
  return (
    <div
      role="alert"
      className="glass-strong pointer-events-auto absolute top-14 left-1/2 flex -translate-x-1/2 items-center gap-3 border border-danger/60 px-4 py-2 text-sm"
      style={{ zIndex: 'var(--z-dialog)' }}
      data-testid="killswitch-banner"
    >
      <OctagonX className="size-4 text-danger" aria-hidden />
      <span className="text-ink-1">
        Kill switch engaged: every agent is stopped and nothing leaves this machine.
      </span>
      {available && (
        <Button onClick={release} title="Opens a confirmation dialog">
          Release…
        </Button>
      )}
    </div>
  );
}
