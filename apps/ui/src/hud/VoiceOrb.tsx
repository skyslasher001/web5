// The voice orb (SPEC §11): bottom center, beside Core's chat orb (alone in zen mode). Idle, listening (a live waveform), thinking, speaking. Hold it (or
// Space) to talk in push-to-talk mode; the small buttons switch the mic, record a memo and open Voice settings.
// The mic itself belongs to Electron main: if the consent patch isn't applied, the orb says so and stays off.
import { Circle, Mic, MicOff, Settings2, Square } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { bridge } from '../lib/bridge';
import { typing } from '../lib/hotkeys';
import { voice } from '../lib/voice';
import { useVoice, type OrbState } from '../lib/voiceClient';
import { useUniverse } from '../state/store';

const LABEL: Record<OrbState, string> = {
  off: 'Voice is off',
  idle: 'Ready',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
};
const MODE_HINT = {
  push_to_talk: 'Hold the orb or Space to talk',
  wake: 'Say "Hey Universe"',
  continuous: 'Listening for anything',
};

/** Wires voice to the app once: consent from main, the kill switch, Core's chat events. */
function useVoiceSetup() {
  const api = useApi();
  useEffect(() => {
    const v = voice(api)!;
    const b = bridge();
    let off: (() => void) | null = null;
    b.getConsent().then(
      (consent) => useVoice.getState().set({ consent }),
      () => {},
    );
    off = b.onConsent((consent) => {
      useVoice.getState().set({ consent });
      v.consentChanged(consent.mic);
    });
    // The kill switch stops capture here too (main also stops it first, and Core stops the voice process).
    const offKill = useUniverse.subscribe((s, prev) => {
      if (s.killSwitch.engaged && !prev.killSwitch.engaged) {
        void v.micOff().catch(() => {});
        v.shutdown();
      }
    });
    return () => {
      off?.();
      offKill();
      v.shutdown();
    };
  }, [api]);
}

/** Space held = push to talk (when the mic is on, the mode is push-to-talk and you're not typing). */
function usePushToTalkKey() {
  useEffect(() => {
    let held = false;
    const down = (e: KeyboardEvent) => {
      const s = useVoice.getState();
      if (e.code !== 'Space' || e.repeat || typing(e.target) || !s.micOn || s.mode !== 'push_to_talk') return;
      e.preventDefault();
      held = true;
      voice()?.client.push(true);
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || !held) return;
      e.preventDefault();
      held = false;
      voice()?.client.push(false);
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, []);
}

function Waveform({ levels }: { levels: number[] }) {
  return (
    <div className="flex h-6 items-center gap-[2px]" aria-hidden>
      {levels.slice(-16).map((l, i) => (
        <span
          key={i}
          className="w-[3px] rounded-full bg-ink-1"
          style={{
            height: `${Math.max(3, Math.min(24, 3 + l * 60))}px`,
            opacity: 0.5 + Math.min(0.5, l * 2),
          }}
        />
      ))}
    </div>
  );
}

/** Mounted once for the whole HUD (the orb itself moves between the dock and zen mode). */
export function VoiceRuntime() {
  useVoiceSetup();
  usePushToTalkKey();
  // For the end-to-end tests: hand the router a sentence as if Whisper had heard it, and read the result.
  useEffect(() => {
    const w = window as unknown as Record<string, Record<string, unknown>>;
    w.__universeDebug = {
      ...(w.__universeDebug ?? {}),
      voiceHeard: (text: string) => voice()?.handle(text),
      voiceState: () => {
        const { state, reply, heard, mode, micOn, error } = useVoice.getState();
        const { selectedProjectId, viewerItemId, panel, view } = useUniverse.getState();
        return { state, reply, heard, mode, micOn, error, selectedProjectId, viewerItemId, panel, view };
      },
    };
  }, []);
  return null;
}

export function VoiceOrb({ floating = false }: { floating?: boolean }) {
  const { state, micOn, mode, levels, heard, reply, memo, dictation, consent, error } = useVoice();
  const pressed = useRef(false);
  const v = voice();

  const toggleMic = () => attempt('Microphone', v?.toggleMic() ?? Promise.resolve());
  const holdable = micOn && mode === 'push_to_talk';
  const ring = {
    off: 'border-hairline-2 bg-space-2/80',
    idle: 'border-accent/50 bg-space-2/90',
    listening: 'border-accent bg-accent/25 shadow-[0_0_24px_var(--color-accent)]',
    thinking: 'border-violet bg-violet/20 orb-breathe',
    speaking: 'border-cyan bg-cyan/20 orb-speak',
  }[state];

  return (
    <div
      className={`pointer-events-auto flex flex-col items-center gap-2 ${
        floating ? 'absolute bottom-5 left-1/2 -translate-x-1/2' : ''
      }`}
      data-testid="voice-orb-root"
    >
      {(heard || reply || error) && (
        <div
          className="glass max-w-md px-3 py-2 text-center text-xs"
          aria-live="polite"
          data-testid="voice-bubble"
        >
          {heard && <p className="text-ink-2">“{heard}”</p>}
          {reply && <p className="mt-1 line-clamp-3 text-ink-1">{reply}</p>}
          {error && !reply && <p className="mt-1 text-amber">{error}</p>}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={toggleMic}
          onMouseDown={(e) => e.preventDefault()} // keep the caret where it is (dictation)
          aria-pressed={micOn}
          aria-label={micOn ? 'Turn the microphone off' : 'Turn the microphone on'}
          title={consent.available ? undefined : (consent.reason ?? undefined)}
          className={`glass flex size-8 items-center justify-center rounded-full ${micOn ? 'text-danger' : 'text-ink-3'}`}
          data-testid="voice-mic"
        >
          {micOn ? <Mic className="size-4" aria-hidden /> : <MicOff className="size-4" aria-hidden />}
        </button>
        <button
          type="button"
          aria-label={`${LABEL[state]}. ${holdable ? MODE_HINT.push_to_talk : micOn ? MODE_HINT[mode] : 'Turn the mic on to talk'}`}
          data-testid="voice-orb"
          data-state={state}
          onMouseDown={(e) => e.preventDefault()}
          onPointerDown={() => {
            if (!holdable) return;
            pressed.current = true;
            v?.client.push(true);
          }}
          onPointerUp={() => {
            if (!pressed.current) return;
            pressed.current = false;
            v?.client.push(false);
          }}
          onPointerLeave={() => {
            if (!pressed.current) return;
            pressed.current = false;
            v?.client.push(false);
          }}
          onClick={() => {
            if (state === 'speaking') v?.stop();
            else if (!micOn) toggleMic();
          }}
          className={`flex size-14 items-center justify-center rounded-full border-2 backdrop-blur transition-all duration-200 ${ring}`}
        >
          {state === 'listening' ? (
            <Waveform levels={levels} />
          ) : (
            <span
              className={`size-3 rounded-full ${state === 'off' ? 'bg-ink-3' : 'bg-ink-1'}`}
              aria-hidden
            />
          )}
        </button>
        <button
          type="button"
          onClick={() =>
            attempt(
              'Memo',
              memo ? (v?.finishMemo(0) ?? Promise.resolve()) : (v?.startMemo() ?? Promise.resolve()),
            )
          }
          aria-label={memo ? 'Save the memo' : 'Record a voice memo'}
          className={`glass flex size-8 items-center justify-center rounded-full ${memo ? 'text-danger' : 'text-ink-3'}`}
          data-testid="voice-memo"
        >
          {memo ? <Square className="size-3.5" aria-hidden /> : <Circle className="size-3.5" aria-hidden />}
        </button>
        <button
          type="button"
          onClick={() => useUniverse.getState().setPanel('voice')}
          aria-label="Voice settings"
          className="glass flex size-8 items-center justify-center rounded-full text-ink-3"
        >
          <Settings2 className="size-4" aria-hidden />
        </button>
      </div>
      <p className="text-[10px] text-ink-3" data-testid="voice-status">
        {LABEL[state]}
        {micOn && ` · ${MODE_HINT[mode]}`}
        {dictation && ' · dictating'}
        {memo && ' · recording a memo'}
      </p>
    </div>
  );
}
