// The only bridge between the sandboxed renderer and the OS: a fixed, typed API (ARCHITECTURE.md §1.3).
import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';
import type { DesktopState, UniverseBridge } from '@universe/shared-types';
import { CH } from '../main/channels';

const bridge: UniverseBridge = {
  getConfig: () => ipcRenderer.invoke(CH.getConfig),
  getDesktopState: () => ipcRenderer.invoke(CH.getDesktopState),
  onDesktopState: (callback) => {
    const listener = (_event: IpcRendererEvent, state: DesktopState) => callback(state);
    ipcRenderer.on(CH.desktopState, listener);
    return () => ipcRenderer.removeListener(CH.desktopState, listener);
  },
  restartService: (name) => ipcRenderer.invoke(CH.restartService, name),
  killService: (name) => ipcRenderer.invoke(CH.killService, name),
  exitSafeMode: () => ipcRenderer.invoke(CH.exitSafeMode),
  getLogs: (name, lines) => ipcRenderer.invoke(CH.getLogs, name, lines),
  openLogsFolder: () => ipcRenderer.invoke(CH.openLogsFolder),
  reportError: (report) => ipcRenderer.send(CH.reportError, report),
  reload: () => ipcRenderer.send(CH.reload),
};

contextBridge.exposeInMainWorld('universe', bridge);
