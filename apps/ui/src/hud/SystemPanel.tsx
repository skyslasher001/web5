import { tokens } from '@universe/design-tokens';
import type { components } from '@universe/shared-types';
import { useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, CircleAlert, RotateCw } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { attempt } from '../lib/attempt';
import { bridge } from '../lib/bridge';
import { useApi } from '../lib/api-context';
import { formatBytes, formatDuration } from '../lib/format';
import type { AssignableTier } from '../lib/api';
import { useHardware, useModels, useRecommendation, useVaultInfo, useVitals } from '../lib/queries';
import { useUniverse } from '../state/store';
import { QUALITY_LABEL, type QualitySetting } from '../universe/quality';
import { CopyButton, Dot, SectionTitle } from './ui';

type Candidate = components['schemas']['Candidate'];

const SERVICE_COLOR: Record<string, string> = {
  healthy: tokens.color.green,
  external: tokens.color.green,
  starting: tokens.color.amber,
  backoff: tokens.color.amber,
  stopped: tokens.color.slate,
  missing: tokens.color.amber,
  unreachable: tokens.color.amber,
  failed: tokens.color.danger,
};

const SERVICE_LABEL: Record<string, string> = {
  external: 'running (started outside UNIVERSE)',
  backoff: 'restarting',
  missing: 'not installed',
};

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1 text-sm">
      <span className="text-ink-3">{label}</span>
      <span className="truncate text-right font-mono text-xs text-ink-1">{children}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-hairline-1 pb-4 last:border-0">
      <SectionTitle>{title}</SectionTitle>
      {children}
    </section>
  );
}

function Services() {
  const supervisor = useUniverse((s) => s.desktop?.supervisor);
  const [busy, setBusy] = useState(false);
  if (!supervisor) return <p className="text-xs text-ink-3">Waiting for the supervisor…</p>;
  return (
    <div className="space-y-2" data-testid="services">
      {Object.entries(supervisor.services).map(([name, svc]) => (
        <div key={name} className="flex items-center gap-3 text-sm">
          <Dot color={SERVICE_COLOR[svc.state] ?? tokens.color.slate} />
          <span className="w-16 capitalize">{name}</span>
          <span className="flex-1 text-xs text-ink-2">
            {SERVICE_LABEL[svc.state] ?? svc.state}
            {svc.restarts ? ` · ${svc.restarts} restart${svc.restarts > 1 ? 's' : ''}` : ''}
          </span>
          {name === 'core' && (
            <button
              type="button"
              disabled={busy}
              title="Restart Core"
              onClick={() => {
                setBusy(true);
                attempt(
                  'Restart Core',
                  bridge()
                    .restartService('core')
                    .finally(() => setBusy(false)),
                );
              }}
              className="text-ink-3 hover:text-accent disabled:opacity-40"
            >
              <RotateCw className="size-3.5" aria-label="Restart Core" />
            </button>
          )}
        </div>
      ))}
      {supervisor.services.ollama?.state === 'missing' && (
        <p className="rounded-md border border-amber/30 p-2 text-xs leading-relaxed text-ink-2">
          Install Ollama from ollama.com/download, then pull a chat model (suggestions below). UNIVERSE starts
          it for you.
        </p>
      )}
    </div>
  );
}

function ChatModel() {
  const api = useApi();
  const models = useModels();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const data = models.data;
  if (!data) return <p className="text-xs text-ink-3">Loading…</p>;
  const chatModels = data.installed.filter((m) => m.capabilities.includes('completion'));
  return (
    <div className="space-y-2">
      {data.chat_model ? (
        <p className="flex items-center gap-2 text-sm">
          <CheckCircle2 className="size-4 text-green" aria-hidden />
          <span className="font-mono text-xs">{data.chat_model}</span>
        </p>
      ) : (
        <div className="space-y-1 rounded-md border border-amber/30 p-2 text-xs">
          <p className="flex items-center gap-2 text-amber">
            <CircleAlert className="size-3.5" aria-hidden /> {data.chat_model_error}
          </p>
          {data.chat_model_hint && (
            <p className="flex items-center justify-between gap-2 font-mono text-ink-2">
              {data.chat_model_hint}
              {data.chat_model_hint.startsWith('Run: ') && (
                <CopyButton text={data.chat_model_hint.slice(5)} />
              )}
            </p>
          )}
        </div>
      )}
      {chatModels.length > 1 && (
        <label className="block text-xs text-ink-3">
          Use for chat
          <select
            className="mt-1 w-full rounded-md border border-hairline-2 bg-space-2 px-2 py-1.5 font-mono text-xs text-ink-1"
            value={data.chat_model ?? ''}
            onChange={(e) => {
              setError(null);
              api
                .assignModel('local-fast', e.target.value)
                .then(() => client.invalidateQueries({ queryKey: ['models'] }))
                .catch((err: Error) => setError(err.message));
            }}
          >
            {chatModels.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name} {m.parameter_size ? `· ${m.parameter_size}` : ''}
              </option>
            ))}
          </select>
        </label>
      )}
      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  );
}

function ModelSelect({
  tier,
  label,
  capability,
  emptyLabel,
  help,
}: {
  tier: AssignableTier;
  label: string;
  capability: string;
  emptyLabel: string;
  help: string;
}) {
  const api = useApi();
  const models = useModels();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const data = models.data;
  if (!data) return null;
  const options = data.installed.filter((m) => m.capabilities.includes(capability));
  const current = data.assignments[tier] ?? '';
  return (
    <label className="block text-xs text-ink-3">
      {label}
      <select
        aria-label={label}
        data-testid={`model-${tier}`}
        className="mt-1 w-full rounded-md border border-hairline-2 bg-space-2 px-2 py-1.5 font-mono text-xs text-ink-1"
        value={current}
        onChange={(e) => {
          setError(null);
          const value = e.target.value;
          (value ? api.assignModel(tier, value) : api.clearModel(tier))
            .then(() => client.invalidateQueries({ queryKey: ['models'] }))
            .catch((err: Error) => setError(err.message));
        }}
      >
        <option value="">{emptyLabel}</option>
        {current && !options.some((m) => m.name === current) && (
          <option value={current}>{current} (not installed)</option>
        )}
        {options.map((m) => (
          <option key={m.name} value={m.name}>
            {m.name}
          </option>
        ))}
      </select>
      <span className="mt-1 block text-[11px] leading-relaxed">{help}</span>
      {error && <span className="block text-danger">{error}</span>}
    </label>
  );
}

function SearchModels() {
  const info = useVaultInfo(true);
  const embedder = info.data?.embedder;
  return (
    <div className="space-y-3" data-testid="search-models">
      <p className="text-xs leading-relaxed text-ink-2">
        {embedder ? (
          <>
            Searching by meaning with <span className="font-mono text-ink-1">{embedder}</span>.
          </>
        ) : (
          <span className="text-amber">
            Keyword search only: install an embedding model (ollama pull nomic-embed-text) to search by
            meaning.
          </span>
        )}
      </p>
      <ModelSelect
        tier="embed_text"
        label="Embedding model"
        capability="embedding"
        emptyLabel="Automatic (first installed)"
        help="Changing it re-indexes the vault in the background; keyword search keeps working meanwhile."
      />
      <ModelSelect
        tier="vision"
        label="Image captions"
        capability="vision"
        emptyLabel="Off"
        help="Describes photos so you can find them by what's in them. Slow on a CPU; off until you choose a model."
      />
    </div>
  );
}

function CandidateRow({ c }: { c: Candidate }) {
  return (
    <li className="flex items-center justify-between gap-2 py-1">
      <span>
        <span className="block font-mono text-xs text-ink-1">{c.tag}</span>
        <span className="block text-[11px] text-ink-3">
          {c.family} · {c.license}
          {c.approx_download_gb ? ` · ~${c.approx_download_gb} GB` : ''}
        </span>
      </span>
      {c.installed ? (
        <span className="text-[11px] text-green">installed</span>
      ) : (
        <CopyButton text={`ollama pull ${c.tag}`} label="Copy pull" />
      )}
    </li>
  );
}

function HardwareAndModels() {
  const hardware = useHardware(true);
  const rec = useRecommendation(true);
  const hw = hardware.data;
  return (
    <>
      <Section title="Hardware">
        {hw ? (
          <div data-testid="hardware">
            <Row label="CPU">{hw.cpu_model}</Row>
            <Row label="Cores">
              {hw.cpu_cores ?? '?'} / {hw.cpu_threads ?? '?'} threads
            </Row>
            <Row label="RAM">{formatBytes(hw.ram_bytes)}</Row>
            {hw.gpus.length === 0 && <Row label="GPU">none detected</Row>}
            {hw.gpus.map((g) => (
              <Row key={g.name} label="GPU">
                {g.name} · {formatBytes(g.vram_bytes)}
              </Row>
            ))}
          </div>
        ) : (
          <p className="text-xs text-ink-3">Detecting…</p>
        )}
      </Section>
      <Section title="Recommended models">
        {rec.data ? (
          <div className="space-y-3">
            <p className="text-xs leading-relaxed text-ink-2">
              <span className="text-ink-1">{rec.data.tier_label}</span>: {rec.data.reason}.
            </p>
            {rec.data.warnings.map((w) => (
              <p key={w} className="text-xs text-amber">
                {w}
              </p>
            ))}
            <div>
              <p className="text-[11px] text-ink-3">Fast (everyday chat)</p>
              <ul>
                {rec.data.local_fast.map((c) => (
                  <CandidateRow key={c.tag} c={c} />
                ))}
              </ul>
            </div>
            <div>
              <p className="text-[11px] text-ink-3">Large (harder tasks)</p>
              <ul>
                {rec.data.local_large.map((c) => (
                  <CandidateRow key={c.tag} c={c} />
                ))}
              </ul>
            </div>
            {!rec.data.verified && (
              <p className="text-[11px] leading-relaxed text-ink-3">
                Shortlist from web research (2026-10-12). Check each model card before relying on it.
              </p>
            )}
          </div>
        ) : (
          <p className="text-xs text-ink-3">Loading…</p>
        )}
      </Section>
    </>
  );
}

const TEXT_SIZES = [
  { value: 1, label: 'Default' },
  { value: 1.125, label: 'Larger' },
  { value: 1.25, label: 'Largest' },
];

function Display() {
  const smooth = useUniverse((s) => s.smooth);
  const setSmooth = useUniverse((s) => s.setSmooth);
  const qualitySetting = useUniverse((s) => s.qualitySetting);
  const quality = useUniverse((s) => s.quality);
  const setQualitySetting = useUniverse((s) => s.setQualitySetting);
  const textScale = useUniverse((s) => s.textScale);
  const setTextScale = useUniverse((s) => s.setTextScale);
  const highContrast = useUniverse((s) => s.highContrast);
  const setHighContrast = useUniverse((s) => s.setHighContrast);
  return (
    <div className="space-y-3">
      <label className="flex items-center justify-between gap-3 text-xs text-ink-2">
        <span>
          Universe quality
          <span className="block text-[11px] text-ink-3">
            {qualitySetting === 'auto' && quality
              ? `Auto: ${QUALITY_LABEL[quality]} for this machine`
              : 'Lite is a 2D graph'}
          </span>
        </span>
        <select
          value={qualitySetting}
          onChange={(e) => setQualitySetting(e.target.value as QualitySetting)}
          className="rounded-md border border-hairline-2 bg-space-2 px-2 py-1 text-xs text-ink-1"
          data-testid="quality"
        >
          {(['auto', 'ultra', 'high', 'balanced', 'lite'] as const).map((q) => (
            <option key={q} value={q}>
              {QUALITY_LABEL[q]}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center justify-between gap-3 text-xs text-ink-2">
        Text size
        <select
          value={textScale}
          onChange={(e) => setTextScale(Number(e.target.value))}
          className="rounded-md border border-hairline-2 bg-space-2 px-2 py-1 text-xs text-ink-1"
          data-testid="text-size"
        >
          {TEXT_SIZES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2 text-xs text-ink-2">
        <input
          type="checkbox"
          checked={highContrast}
          onChange={(e) => setHighContrast(e.target.checked)}
          className="accent-[var(--color-accent)]"
          data-testid="high-contrast"
        />
        High contrast
      </label>
      <label className="flex items-start gap-2 text-xs text-ink-2">
        <input
          type="checkbox"
          checked={smooth}
          onChange={(e) => setSmooth(e.target.checked)}
          className="mt-0.5 accent-[var(--color-accent)]"
          data-testid="smooth-mode"
        />
        <span>
          Smooth mode
          <span className="block text-[11px] leading-relaxed text-ink-3">
            Turns off the glass blur and renders the universe at 1× for steadier frames. It switches on by
            itself when this display drops frames.
          </span>
        </span>
      </label>
    </div>
  );
}

export function SystemPanel() {
  const vitals = useVitals(true);
  const v = vitals.data;
  return (
    <div className="space-y-4">
      <Section title="Core">
        {v ? (
          <div data-testid="vitals">
            <Row label="Status">{v.safe_mode ? 'safe mode' : 'running'}</Row>
            <Row label="Uptime">{formatDuration(v.uptime_s)}</Row>
            <Row label="Memory">{formatBytes(v.rss_bytes)}</Row>
            <Row label="Process">pid {v.pid}</Row>
            <Row label="Events">#{v.event_seq}</Row>
            <Row label="Version">
              {v.version} · Python {v.python}
            </Row>
          </div>
        ) : (
          <p className="text-xs text-ink-3">Core is not reachable.</p>
        )}
      </Section>
      <Section title="Services">
        <Services />
      </Section>
      <Section title="Chat model">
        <ChatModel />
      </Section>
      <Section title="Search models">
        <SearchModels />
      </Section>
      <Section title="Display">
        <Display />
      </Section>
      <HardwareAndModels />
    </div>
  );
}
