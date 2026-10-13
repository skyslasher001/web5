import {
  Camera,
  Cpu,
  Grid2x2,
  List,
  LoaderCircle,
  Mic,
  MonitorUp,
  Orbit,
  Pause,
  Search,
  X,
} from 'lucide-react';
import { tokens } from '@universe/design-tokens';
import { useEffect, useRef } from 'react';
import { formatUsd } from '../lib/format';
import { useBudget, useEngine, useModels, useQueueStats, useVitals } from '../lib/queries';
import { useInteraction } from '../universe/scene/interaction';
import { useScene } from '../universe/scene/sceneData';
import { formatBytes } from '../lib/format';
import { useUniverse, type View } from '../state/store';
import { KillSwitchButton } from './KillSwitch';
import { Dot, Kbd } from './ui';

/** Spend this month against your cap. Until the policy engine is installed, everything is local and free. */
function BudgetMeter() {
  const engine = useEngine();
  const budget = useBudget(!!engine.data?.available);
  const setPanel = useUniverse((s) => s.setPanel);
  const data = budget.data;
  const over = data && data.monthly_cap_usd > 0 && data.spent_usd >= data.monthly_cap_usd * 0.8;
  return (
    <button
      type="button"
      onClick={() => setPanel('safety')}
      className={`font-mono text-xs ${over ? 'text-amber' : 'text-ink-3'} hover:text-ink-1`}
      title={
        data
          ? `Spent this month: ${formatUsd(data.spent_usd)} of a ${formatUsd(data.monthly_cap_usd)} cap · ${data.calls} model calls`
          : 'Spend this month: everything runs locally'
      }
      data-testid="budget-meter"
    >
      {data && data.spent_usd > 0
        ? `${formatUsd(data.spent_usd)} / ${formatUsd(data.monthly_cap_usd)}`
        : '$0.00 · local'}
    </button>
  );
}

/** System vitals in the status cluster: Core's CPU and memory (System panel has the rest). */
function VitalsChip() {
  const vitals = useVitals(true);
  const setPanel = useUniverse((s) => s.setPanel);
  if (!vitals.data) return null;
  return (
    <button
      type="button"
      onClick={() => setPanel('system')}
      className="font-mono text-xs text-ink-3 hover:text-ink-1"
      title="Core's CPU and memory (System → Vitals)"
      data-testid="vitals-chip"
    >
      CPU {Math.round(vitals.data.cpu_percent)}% · {formatBytes(vitals.data.rss_bytes)}
    </button>
  );
}

function CoreChip() {
  const connection = useUniverse((s) => s.connection);
  const safeMode = useUniverse((s) => s.desktop?.supervisor?.safe_mode.active ?? false);
  const [color, label] = safeMode
    ? [tokens.color.danger, 'Safe mode']
    : connection === 'online'
      ? [tokens.color.green, 'Core online']
      : [tokens.color.amber, connection === 'connecting' ? 'Connecting…' : 'Reconnecting…'];
  return (
    <span className="flex items-center gap-2 text-xs text-ink-2" data-testid="core-status">
      <Dot color={color} pulse={connection !== 'online' || safeMode} />
      {label}
    </span>
  );
}

function ModelChip() {
  const models = useModels();
  const name = models.data?.chat_model;
  return (
    <span
      className={`flex items-center gap-1.5 font-mono text-xs ${name ? 'text-ink-2' : 'text-amber'}`}
      title={
        name ? 'Chat model (local, via Ollama)' : (models.data?.chat_model_hint ?? 'No chat model installed')
      }
    >
      <Cpu className="size-3.5" aria-hidden />
      {name ?? 'no model'}
    </span>
  );
}

/** Background work: shown only while there's something queued, or when the governor paused it. */
function IndexingChip() {
  const stats = useQueueStats().data;
  const setPanel = useUniverse((s) => s.setPanel);
  if (!stats) return null;
  const pending = stats.queued + stats.leased;
  if (stats.paused && pending > 0) {
    return (
      <button
        type="button"
        onClick={() => setPanel('vault')}
        className="flex items-center gap-1.5 text-xs text-amber"
        title={stats.pause_reason ?? 'Background work is paused'}
        data-testid="indexing-chip"
      >
        <Pause className="size-3.5" aria-hidden /> Paused · {pending}
      </button>
    );
  }
  if (pending === 0) return null;
  return (
    <button
      type="button"
      onClick={() => setPanel('vault')}
      className="flex items-center gap-1.5 text-xs text-ink-2"
      title={
        stats.model_hold ? 'Waiting while you chat, then indexing' : 'Indexing your vault in the background'
      }
      data-testid="indexing-chip"
    >
      <LoaderCircle className="size-3.5 orb-spin text-accent-2" aria-hidden /> Indexing {pending}
    </button>
  );
}

function SearchField() {
  const query = useUniverse((s) => s.query);
  const setQuery = useUniverse((s) => s.setQuery);
  const setPaletteOpen = useUniverse((s) => s.setPaletteOpen);
  const focusTick = useUniverse((s) => s.searchFocusTick);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusTick === 0) return;
    input.current?.focus();
    input.current?.select();
  }, [focusTick]);
  return (
    <div className="no-drag glass flex h-8 w-[min(34rem,100%)] items-center gap-3 rounded-full px-4 text-sm transition-colors duration-150 focus-within:border-accent/50 hover:border-hairline-2">
      <Search className="size-4 shrink-0 text-ink-3" aria-hidden />
      <input
        ref={input}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            if (query) setQuery('');
            else e.currentTarget.blur();
          } else if (e.key === 'Enter' || e.key === 'ArrowDown') {
            e.preventDefault();
            const s = useUniverse.getState();
            const top = useInteraction.getState().results[0];
            const id = top !== undefined ? useScene.getState().scene.ids[top] : undefined;
            // In the universe, Enter flies to the best match; otherwise hand the keyboard to the results list.
            if (e.key === 'Enter' && s.view === 'universe' && id) s.selectItem(id);
            else s.focusResults();
          }
        }}
        placeholder="Search your vault…"
        aria-label="Search your vault"
        data-testid="search-input"
        spellCheck={false}
        className="min-w-0 flex-1 bg-transparent text-ink-1 placeholder:text-ink-3 focus:outline-none"
      />
      {query && (
        <button
          type="button"
          aria-label="Clear search"
          onClick={() => setQuery('')}
          className="text-ink-3 hover:text-ink-2"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      )}
      <button type="button" title="Commands" onClick={() => setPaletteOpen(true)} className="shrink-0">
        <Kbd>Ctrl K</Kbd>
      </button>
    </div>
  );
}

const VIEWS: { view: View; label: string; key: string; Icon: typeof List }[] = [
  { view: 'universe', label: 'Universe', key: 'U', Icon: Orbit },
  { view: 'grid', label: 'Grid', key: 'G', Icon: Grid2x2 },
  { view: 'list', label: 'List', key: 'L', Icon: List },
];

function ViewSwitch() {
  const view = useUniverse((s) => s.view);
  const setView = useUniverse((s) => s.setView);
  return (
    <div
      className="no-drag glass flex h-8 items-center gap-0.5 rounded-full px-1"
      role="group"
      aria-label="View"
    >
      {VIEWS.map(({ view: v, label, key, Icon }) => (
        <button
          key={v}
          type="button"
          title={`${label} (${key})`}
          aria-pressed={view === v}
          data-testid={`view-${v}`}
          onClick={() => setView(v)}
          className={`rounded-full p-1.5 transition-colors duration-150 ${
            view === v ? 'bg-space-3 text-ink-1' : 'text-ink-3 hover:text-ink-2'
          }`}
        >
          <Icon className="size-3.5" aria-label={`${label} view`} />
        </button>
      ))}
    </div>
  );
}

function ConsentOff() {
  const items = [
    { Icon: Mic, label: 'Microphone off' },
    { Icon: MonitorUp, label: 'Screen capture off' },
    { Icon: Camera, label: 'Camera off' },
  ];
  return (
    <span
      className="flex items-center gap-2 text-ink-3"
      aria-label="Capture: microphone, screen and camera are off"
    >
      {items.map(({ Icon, label }) => (
        <span key={label} title={`${label}: nothing is being captured`}>
          <Icon className="size-3.5" aria-hidden />
        </span>
      ))}
    </span>
  );
}

export function TopBar() {
  const controlsWidth = useUniverse((s) => s.config?.windowControlsWidth ?? 0);
  return (
    <header
      className="drag pointer-events-auto absolute inset-x-0 top-0 flex h-12 items-center gap-6 pl-5"
      style={{ paddingRight: controlsWidth + 20 }}
    >
      <div className="flex items-center gap-2.5">
        <Orbit className="size-5 text-accent" aria-hidden />
        <span className="font-display text-sm font-semibold tracking-[0.32em]">UNIVERSE</span>
      </div>
      <div className="flex flex-1 items-center justify-center gap-2">
        <SearchField />
        <ViewSwitch />
      </div>
      <div className="no-drag flex items-center gap-3 whitespace-nowrap">
        <IndexingChip />
        <CoreChip />
        <ModelChip />
        <VitalsChip />
        <BudgetMeter />
        <ConsentOff />
        <KillSwitchButton />
      </div>
    </header>
  );
}
