import { LoaderCircle, Orbit } from 'lucide-react';
import { lazy, Suspense } from 'react';
import { CoreProvider } from './lib/core';
import { useHotkeys } from './lib/hotkeys';
import { useUniverse } from './state/store';
import { ActivityRibbon } from './hud/ActivityRibbon';
import { AgentDock } from './hud/AgentDock';
import { ChatDock } from './hud/ChatDock';
import { CommandPalette } from './hud/CommandPalette';
import { ConnectionBanner } from './hud/ConnectionBanner';
import { ConsentIndicators } from './hud/ConsentIndicators';
import { SidePanel } from './hud/SidePanel';
import { TopBar } from './hud/TopBar';
import { ErrorBoundary } from './hud/ErrorBoundary';

// three.js is most of the bundle: load it after the HUD so the shell is usable first (SPEC §24).
const Scene = lazy(() => import('./universe/Scene'));

function Booting({ error }: { error: string | null }) {
  return (
    <div className="space-backdrop flex h-full flex-col items-center justify-center gap-4">
      <Orbit className="size-10 text-accent" aria-hidden />
      <p className="font-display text-lg tracking-[0.3em] text-ink-1">UNIVERSE</p>
      {error ? (
        <p role="alert" className="max-w-md text-center text-sm text-danger">
          {error}
        </p>
      ) : (
        <p className="flex items-center gap-2 text-sm text-ink-2">
          <LoaderCircle className="size-4 orb-spin" aria-hidden /> Starting…
        </p>
      )}
    </div>
  );
}

function Hud() {
  useHotkeys();
  const zen = useUniverse((s) => s.zen);
  return (
    <div className="relative h-full w-full overflow-hidden select-none">
      <div className="space-backdrop absolute inset-0" aria-hidden />
      <ErrorBoundary name="universe" fallback={null}>
        <Suspense fallback={null}>
          <Scene />
        </Suspense>
      </ErrorBoundary>
      <div className="pointer-events-none absolute inset-0" style={{ zIndex: 'var(--z-hud)' }}>
        {zen ? (
          <p className="absolute bottom-6 left-1/2 -translate-x-1/2 text-xs text-ink-3">
            Zen mode · press Z or Esc to return
          </p>
        ) : (
          <>
            <TopBar />
            <ConnectionBanner />
            <AgentDock />
            <SidePanel />
            <ActivityRibbon />
            <ChatDock />
          </>
        )}
      </div>
      <ConsentIndicators />
      <CommandPalette />
    </div>
  );
}

export function App() {
  return (
    <CoreProvider fallback={(error) => <Booting error={error} />}>
      <ErrorBoundary name="hud" fallback={<Booting error="The interface hit an error; it was recorded." />}>
        <Hud />
      </ErrorBoundary>
    </CoreProvider>
  );
}
