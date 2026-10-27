// Voice settings (SPEC §11): turn voice on, install the models (downloaded through the egress gate, checked
// against pinned SHA-256s), pick the mode and wake phrase, the voices (one per agent), and see the latency of the
// last answer. Everything runs on this machine; nothing you say is stored unless you save a memo.
import type { VoiceModelInfo, VoiceSettingsUpdate } from '@universe/shared-types';
import { useQueryClient } from '@tanstack/react-query';
import { Download, Play, Power } from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { formatBytes } from '../lib/format';
import { useVoices, useVoiceStatus } from '../lib/queries';
import { voice } from '../lib/voice';
import { useVoice } from '../lib/voiceClient';
import type { VoiceMode } from '../lib/voiceCommands';
import { Button, Dot, inputClass, Section } from './ui';

const MODES: { id: VoiceMode; label: string; hint: string }[] = [
  { id: 'push_to_talk', label: 'Push to talk', hint: 'Hold the orb or Space while you talk.' },
  {
    id: 'wake',
    label: 'Wake word',
    hint: 'Start with the wake phrase, e.g. "Hey Universe, go to Ember Wolf".',
  },
  {
    id: 'continuous',
    label: 'Continuous',
    hint: 'Every sentence counts; after 30 s of quiet it goes back to wake word.',
  },
];

function ModelRow({ model }: { model: VoiceModelInfo }) {
  const api = useApi();
  const qc = useQueryClient();
  const busy = model.install_state === 'downloading' || model.install_state === 'installing';
  const pct = model.size ? Math.round((model.install_done / model.size) * 100) : 0;
  return (
    <li className="flex items-start justify-between gap-2 text-xs" data-testid={`voice-model-${model.id}`}>
      <div className="min-w-0">
        <p className="text-ink-1">{model.title}</p>
        <p className="text-[10px] text-ink-3">
          {model.license} · {formatBytes(model.size)}
        </p>
        {model.install_state === 'failed' && <p className="text-[10px] text-danger">{model.install_error}</p>}
      </div>
      {model.installed ? (
        <span className="flex items-center gap-1 text-[11px] text-green">
          <Dot color="var(--color-green)" /> Installed
        </span>
      ) : busy ? (
        <span className="text-[11px] text-ink-2">
          {model.install_state === 'installing' ? 'Verifying…' : `${pct}%`}
        </span>
      ) : (
        <Button
          onClick={() =>
            attempt(
              'Install',
              api.installVoiceModel(model.id).then(() => qc.invalidateQueries({ queryKey: ['voice'] })),
            )
          }
          testid={`install-${model.id}`}
        >
          <Download className="size-3.5" aria-hidden /> Install
        </Button>
      )}
    </li>
  );
}

export function VoicePanel() {
  const api = useApi();
  const qc = useQueryClient();
  const status = useVoiceStatus();
  const voices = useVoices();
  const { connected, consent, latencyMs, dictation, micOn } = useVoice();
  const [phrase, setPhrase] = useState<string | null>(null);
  const v = voice();
  const s = status.data;
  if (!s) return <p className="text-xs text-ink-3">Loading voice…</p>;

  const update = (body: VoiceSettingsUpdate) =>
    attempt(
      'Voice settings',
      api.voiceSettings(body).then(async (next) => {
        qc.setQueryData(['voice', 'status'], next);
        await qc.invalidateQueries({ queryKey: ['voice', 'voices'] });
        if (body.mode) v?.client.setMode(body.mode as VoiceMode);
        if (body.speed) v?.setSpeed(body.speed);
        await v?.refreshVoices();
      }),
    );
  const installedStt = s.models.some((m) => m.kind === 'stt' && m.installed);
  const installedTts = s.models.some((m) => m.kind === 'tts' && m.installed);
  const available = s.voices.length ? s.voices : (voices.data?.voices ?? []);

  return (
    <div className="space-y-4" data-testid="voice-panel">
      <Section title="Voice">
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="flex items-center gap-2 text-ink-2">
            <Dot
              color={
                s.state === 'ready'
                  ? 'var(--color-green)'
                  : s.state === 'failed'
                    ? 'var(--color-danger)'
                    : 'var(--color-slate)'
              }
            />
            {s.state === 'ready' ? `On · ${s.stt ?? 'no speech-to-text'} · ${s.tts ?? 'no voice'}` : s.state}
          </span>
          {s.state === 'ready' || connected ? (
            <Button
              onClick={() =>
                attempt(
                  'Voice',
                  (async () => {
                    v?.shutdown();
                    await api.voiceStop();
                    await qc.invalidateQueries({ queryKey: ['voice'] });
                  })(),
                )
              }
            >
              <Power className="size-3.5" aria-hidden /> Turn off
            </Button>
          ) : (
            <Button
              tone="primary"
              onClick={() =>
                attempt(
                  'Voice',
                  (v?.connect() ?? Promise.resolve()).then(() =>
                    qc.invalidateQueries({ queryKey: ['voice'] }),
                  ),
                )
              }
              testid="voice-start"
            >
              <Power className="size-3.5" aria-hidden /> Turn on
            </Button>
          )}
        </div>
        {s.reason && <p className="text-[11px] text-amber">{s.reason}</p>}
        <p className="text-[11px] text-ink-3" data-testid="voice-consent">
          Microphone: {micOn ? 'on (you turned it on)' : `off${consent.reason ? ` · ${consent.reason}` : ''}`}
        </p>
        {latencyMs !== null && (
          <p className="text-[11px] text-ink-3" data-testid="voice-latency">
            Last answer: {latencyMs} ms from the end of your sentence to the first word (target under 1500 ms)
          </p>
        )}
      </Section>

      <Section title="Models">
        {!installedStt && (
          <p className="text-[11px] text-amber">Install a Whisper model to talk to UNIVERSE.</p>
        )}
        {!installedTts && <p className="text-[11px] text-amber">Install Kokoro to hear answers.</p>}
        <ul className="space-y-2">
          {s.models.map((m) => (
            <ModelRow key={m.id} model={m} />
          ))}
        </ul>
        <label className="flex items-center justify-between gap-2 text-xs text-ink-2">
          Speech-to-text
          <select
            value={s.settings.stt ?? ''}
            onChange={(e) => update({ stt: e.target.value || null })}
            className={inputClass}
            aria-label="Speech-to-text model"
          >
            <option value="">Best installed (tiny.en is fastest)</option>
            {s.models
              .filter((m) => m.kind === 'stt')
              .map((m) => (
                <option key={m.id} value={m.id} disabled={!m.installed}>
                  {m.id}
                </option>
              ))}
          </select>
        </label>
      </Section>

      <Section title="Listening">
        <div role="radiogroup" aria-label="Mode" className="space-y-1">
          {MODES.map((m) => (
            <label key={m.id} className="flex items-start gap-2 text-xs">
              <input
                type="radio"
                name="voice-mode"
                checked={s.settings.mode === m.id}
                onChange={() => update({ mode: m.id })}
                data-testid={`voice-mode-${m.id}`}
              />
              <span>
                <span className="text-ink-1">{m.label}</span>
                <span className="block text-[10px] text-ink-3">{m.hint}</span>
              </span>
            </label>
          ))}
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-2">
          Wake phrase
          <input
            value={phrase ?? s.settings.wake_phrase}
            onChange={(e) => setPhrase(e.target.value)}
            onBlur={() => {
              if (phrase && phrase.trim().length >= 3 && phrase !== s.settings.wake_phrase)
                update({ wake_phrase: phrase });
              setPhrase(null);
            }}
            className={`${inputClass} flex-1`}
            aria-label="Wake phrase"
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-ink-2">
          <input
            type="checkbox"
            checked={dictation}
            onChange={(e) => useVoice.getState().set({ dictation: e.target.checked })}
          />
          Dictation: what you say is typed into the focused text field (say "stop dictation" to end)
        </label>
      </Section>

      <Section title="Voices">
        <label className="flex items-center justify-between gap-2 text-xs text-ink-2">
          Speed
          <input
            type="range"
            min={0.7}
            max={1.5}
            step={0.05}
            value={s.settings.speed}
            onChange={(e) => update({ speed: Number(e.target.value) })}
            aria-label="Speaking speed"
          />
          <span className="w-8 text-right text-ink-3">{s.settings.speed.toFixed(2)}×</span>
        </label>
        <ul className="space-y-1.5">
          {(voices.data?.agents ?? []).map((a) => (
            <li key={a.agent_id} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-ink-1">{a.name}</span>
              <span className="flex items-center gap-1">
                <select
                  value={a.voice}
                  onChange={(e) => update({ agents: { ...s.settings.agents, [a.agent_id]: e.target.value } })}
                  className={inputClass}
                  aria-label={`${a.name}'s voice`}
                >
                  {(available.includes(a.voice) ? available : [a.voice, ...available]).map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  aria-label={`Hear ${a.name}`}
                  disabled={!connected}
                  onClick={() => v?.say(`Hi, I'm ${a.name}.`, a.agent_id)}
                  className="rounded p-1 text-ink-3 hover:text-ink-1 disabled:opacity-40"
                >
                  <Play className="size-3.5" aria-hidden />
                </button>
              </span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Privacy">
        <p className="text-[11px] leading-relaxed text-ink-3">
          Voice runs entirely on this computer. The microphone is off every time UNIVERSE starts and only you
          can turn it on; the kill switch turns it off. What you say is transcribed in memory and never stored
          — except a memo you record and save, which goes to the vault and is transcribed there.
        </p>
      </Section>
    </div>
  );
}
