// Always-on-top capture indicators (SPEC §3.4). The mic shows here whenever it's open (Phase 7); Electron main
// shows its own indicator too (the tray), which this page can't hide. Screen and camera come in Phase 8.
import { Mic } from 'lucide-react';
import { useVoice } from '../lib/voiceClient';

export function ConsentIndicators() {
  const micOn = useVoice((s) => s.micOn);
  const memo = useVoice((s) => s.memo);
  return (
    <div
      className="pointer-events-none fixed top-14 right-4 flex flex-col items-end gap-1"
      style={{ zIndex: 'var(--z-consent)' }}
      aria-live="polite"
    >
      {micOn && (
        <span
          className="flex items-center gap-1.5 rounded-full border border-danger/60 bg-space-1/90 px-2.5 py-1 text-[11px] text-danger"
          data-testid="mic-indicator"
        >
          <Mic className="size-3" aria-hidden /> {memo ? 'Recording a memo' : 'Microphone on'}
        </span>
      )}
    </div>
  );
}
