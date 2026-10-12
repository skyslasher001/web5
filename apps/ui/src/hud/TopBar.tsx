import { Camera, Cpu, Mic, MonitorUp, Orbit, Search } from 'lucide-react';
import { tokens } from '@universe/design-tokens';
import { useModels } from '../lib/queries';
import { useUniverse } from '../state/store';
import { Dot, Kbd } from './ui';

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
  const setPaletteOpen = useUniverse((s) => s.setPaletteOpen);
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
      <div className="flex flex-1 justify-center">
        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className="no-drag glass flex h-8 w-[min(34rem,100%)] items-center gap-3 rounded-full px-4 text-sm text-ink-3 transition-colors duration-150 hover:border-hairline-2 hover:text-ink-2"
        >
          <Search className="size-4" aria-hidden />
          <span className="flex-1 text-left">Type a command…</span>
          <Kbd>Ctrl K</Kbd>
        </button>
      </div>
      <div className="no-drag flex items-center gap-4">
        <CoreChip />
        <ModelChip />
        <span className="font-mono text-xs text-ink-3" title="Spend this month: everything runs locally">
          $0.00 · local
        </span>
        <ConsentOff />
      </div>
    </header>
  );
}
