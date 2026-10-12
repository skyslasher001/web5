// IPC channel names shared by main and preload.
export const CH = {
  getConfig: 'universe:get-config',
  getDesktopState: 'universe:get-desktop-state',
  desktopState: 'universe:desktop-state',
  restartService: 'universe:restart-service',
  killService: 'universe:kill-service',
  exitSafeMode: 'universe:exit-safe-mode',
  getLogs: 'universe:get-logs',
  openLogsFolder: 'universe:open-logs-folder',
  reportError: 'universe:report-error',
  reload: 'universe:reload',
} as const;
