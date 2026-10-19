// Boots the connection to Core: bridge config → REST client → WebSocket → store.
import type { FocusTarget } from '@universe/shared-types';
import { useEffect, useState, type ReactNode } from 'react';
import { useUniverse } from '../state/store';
import { CoreApi } from './api';
import { ApiContext } from './api-context';
import { bridge } from './bridge';
import { installErrorReporting } from './errorReporting';
import { CoreSocket } from './socket';
import { voice } from './voice';

/** The command bar asked the main window to show something. */
function applyFocus(target: FocusTarget): void {
  const s = useUniverse.getState();
  if (target.kind === 'item') {
    s.selectItem(target.id);
  } else if (target.kind === 'project') {
    s.selectProject(target.id);
    if (s.view === 'universe') s.setView('grid');
  } else {
    s.setShowTrash(false);
    s.setQuery(target.query);
  }
}

export function CoreProvider({
  children,
  fallback,
}: {
  children: ReactNode;
  fallback: (error: string | null) => ReactNode;
}) {
  const [api, setApi] = useState<CoreApi | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);

  useEffect(() => {
    const store = useUniverse.getState();
    let socket: CoreSocket | null = null;
    let offDesktop: (() => void) | null = null;
    let offFocus: (() => void) | null = null;
    let offKill: (() => void) | null = null;
    const offErrors = installErrorReporting();
    let cancelled = false;
    (async () => {
      const b = bridge();
      const config = await b.getConfig();
      if (cancelled) return;
      store.setConfig(config);
      const client = new CoreApi(config.coreUrl, config.token);
      setApi(client);
      store.setDesktop(await b.getDesktopState());
      offDesktop = b.onDesktopState((state) => useUniverse.getState().setDesktop(state));
      offFocus = b.onFocus(applyFocus);
      store.setKillSwitch(await b.getKillSwitch());
      offKill = b.onKillSwitch((state) => useUniverse.getState().setKillSwitch(state));
      socket = new CoreSocket({
        wsUrl: config.wsUrl,
        lastSeq: () => useUniverse.getState().lastSeq,
        getTicket: async () => {
          if (useUniverse.getState().lastSeq === 0) {
            // First contact: show recent history instead of replaying everything.
            const page = await client.recentEvents(30);
            useUniverse.getState().seedActivity(page.events, page.last_seq);
          }
          return (await client.wsTicket()).ticket;
        },
        onState: (state, attempt) => {
          useUniverse.getState().setConnection(state, attempt);
          if (state === 'online')
            client.agents().then(
              (a) => useUniverse.getState().setAgents(a),
              () => {},
            );
        },
        onEvent: (event) => {
          useUniverse.getState().applyEvent(event);
          // Spoken answers, and approvals read out so you can answer by voice.
          if (event.type.startsWith('chat.') || event.type === 'approval.requested')
            voice()?.onCoreEvent(event);
          // The roster changed (Agents panel): the dock lists the agents that are on.
          if (/^agent\.(added|updated|removed)$/.test(event.type))
            client.agents().then(
              (a) => useUniverse.getState().setAgents(a),
              () => {},
            );
        },
      });
      socket.start();
    })().catch((err: unknown) => setFatal(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
      socket?.stop();
      offDesktop?.();
      offFocus?.();
      offKill?.();
      offErrors();
    };
  }, []);

  if (!api) return <>{fallback(fatal)}</>;
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}
