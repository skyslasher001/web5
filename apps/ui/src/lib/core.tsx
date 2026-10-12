// Boots the connection to Core: bridge config → REST client → WebSocket → store.
import { useEffect, useState, type ReactNode } from 'react';
import { useUniverse } from '../state/store';
import { CoreApi } from './api';
import { ApiContext } from './api-context';
import { bridge } from './bridge';
import { CoreSocket } from './socket';

function installErrorReporting(): () => void {
  const report = (kind: string, message: string, stack?: string) => {
    try {
      bridge().reportError({ kind, message, stack });
    } catch {
      // no bridge (should not happen inside Electron)
    }
  };
  const onError = (e: ErrorEvent) => report(e.error?.name ?? 'Error', e.message, e.error?.stack);
  const onRejection = (e: PromiseRejectionEvent) => {
    const err = e.reason instanceof Error ? e.reason : new Error(String(e.reason));
    report(err.name, err.message, err.stack);
  };
  window.addEventListener('error', onError);
  window.addEventListener('unhandledrejection', onRejection);
  return () => {
    window.removeEventListener('error', onError);
    window.removeEventListener('unhandledrejection', onRejection);
  };
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
        onEvent: (event) => useUniverse.getState().applyEvent(event),
      });
      socket.start();
    })().catch((err: unknown) => setFatal(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
      socket?.stop();
      offDesktop?.();
      offErrors();
    };
  }, []);

  if (!api) return <>{fallback(fatal)}</>;
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}
