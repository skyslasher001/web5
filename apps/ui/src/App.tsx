import { LoaderCircle, Orbit } from 'lucide-react';
import { lazy, Suspense, useEffect } from 'react';
import { CoreProvider } from './lib/core';
import { useFrameBudget } from './lib/frameBudget';
import { useHotkeys } from './lib/hotkeys';
import { useUniverse } from './state/store';
import { ActivityRibbon } from './hud/ActivityRibbon';
import { FilterChips } from './hud/FilterChips';
import { NavigatorCard } from './hud/NavigatorCard';
import { ItemViewer } from './hud/viewers/ItemViewer';
import { AgentDock } from './hud/AgentDock';
import { ApprovalsTray } from './hud/ApprovalsTray';
import { ChatDock } from './hud/ChatDock';
import { CommandPalette } from './hud/CommandPalette';
import { ConnectionBanner } from './hud/ConnectionBanner';
import { ConsentIndicators } from './hud/ConsentIndicators';
import { SidePanel } from './hud/SidePanel';
import { TopBar } from './hud/TopBar';
import { ErrorBoundary } from './hud/ErrorBoundary';
import { DropZone } from './hud/DropZone';
import { KillSwitchBanner } from './hud/KillSwitch';
import { PerfHud } from './hud/PerfHud';
import { VoiceOrb, VoiceRuntime } from './hud/VoiceOrb';
import { ItemsView } from './views2d/ItemsView';

// three.js is most of the bundle: load it after the HUD so the shell is usable first (SPEC §24).
const Scene = lazy(() => import('./universe/Scene'));
// The command bar window loads the same bundle with #command-bar and never touches three.js.
const CommandBarRoot = lazy(() =>
  import('./command/CommandBar').then((m) => ({ default: m.CommandBarRoot })),
);

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
  useFrameBudget();
  // Accessibility choices from last time (text size, high contrast).
  useEffect(() => {
    const s = useUniverse.getState();
    s.setTextScale(s.textScale);
    s.setHighContrast(s.highContrast);
  }, []);
  const zen = useUniverse((s) => s.zen);
  const view = useUniverse((s) => s.view);
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
          <p className="absolute bottom-6 left-6 text-xs text-ink-3">Zen mode · press Z or Esc to return</p>
        ) : (
          <>
            <TopBar />
            <ConnectionBanner />
            <AgentDock />
            <SidePanel />
            {view !== 'universe' && (
              <ErrorBoundary name="items" fallback={null}>
                <ItemsView />
              </ErrorBoundary>
            )}
            {view === 'universe' && <FilterChips />}
            <div className="absolute bottom-4 left-4 flex w-72 flex-col gap-2">
              <ActivityRibbon />
              {view === 'universe' && <NavigatorCard />}
            </div>
            <ChatDock />
            <ItemViewer />
            <ApprovalsTray />
          </>
        )}
        {/* Voice works in every view, zen included: you can run the app by voice alone (SPEC §25 Phase 7). */}
        <ErrorBoundary name="voice" fallback={null}>
          <VoiceRuntime />
          {zen && <VoiceOrb floating />}
        </ErrorBoundary>
        {/* Shown even in zen mode: you should always know that agents are stopped. */}
        <KillSwitchBanner />
        {/* A debug overlay the owner turns on; shown in every view, zen included. */}
        <PerfHud />
      </div>
      <ConsentIndicators />
      <DropZone />
      <CommandPalette />
    </div>
  );
}

export function App() {
  if (window.location.hash === '#command-bar') {
    return (
      <ErrorBoundary
        name="command-bar"
        fallback={<p className="p-4 text-sm text-danger">The command bar hit an error.</p>}
      >
        <Suspense fallback={null}>
          <CommandBarRoot />
        </Suspense>
      </ErrorBoundary>
    );
  }
  return (
    <CoreProvider fallback={(error) => <Booting error={error} />}>
      <ErrorBoundary name="hud" fallback={<Booting error="The interface hit an error; it was recorded." />}>
        <Hud />
      </ErrorBoundary>
    </CoreProvider>
  );
}
