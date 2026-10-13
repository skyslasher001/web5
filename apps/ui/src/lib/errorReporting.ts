// Uncaught renderer errors go to the main process, which files them with Core (SPEC §22).
import { bridge } from './bridge';

export function installErrorReporting(): () => void {
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
