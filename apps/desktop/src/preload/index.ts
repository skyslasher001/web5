// The only bridge between the sandboxed renderer and the OS: a fixed, typed API (ARCHITECTURE.md §1.3).
import { contextBridge, ipcRenderer, webUtils, type IpcRendererEvent } from 'electron';
import type { DesktopState, FocusTarget, UniverseBridge } from '@universe/shared-types';
import { CH } from '../main/channels';

function subscribe<T>(channel: string, callback: (value: T) => void): () => void {
  const listener = (_event: IpcRendererEvent, value: T) => callback(value);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

const bridge: UniverseBridge = {
  getConfig: () => ipcRenderer.invoke(CH.getConfig),
  getDesktopState: () => ipcRenderer.invoke(CH.getDesktopState),
  onDesktopState: (callback) => subscribe<DesktopState>(CH.desktopState, callback),
  restartService: (name) => ipcRenderer.invoke(CH.restartService, name),
  killService: (name) => ipcRenderer.invoke(CH.killService, name),
  exitSafeMode: () => ipcRenderer.invoke(CH.exitSafeMode),
  getLogs: (name, lines) => ipcRenderer.invoke(CH.getLogs, name, lines),
  openLogsFolder: () => ipcRenderer.invoke(CH.openLogsFolder),
  reportError: (report) => ipcRenderer.send(CH.reportError, report),
  reload: () => ipcRenderer.send(CH.reload),

  pathsForFiles: (files) => files.map((file) => webUtils.getPathForFile(file)).filter(Boolean),
  openPath: (absPath) => ipcRenderer.invoke(CH.openPath, absPath),
  revealPath: (absPath) => ipcRenderer.invoke(CH.revealPath, absPath),
  pickFolder: (title) => ipcRenderer.invoke(CH.pickFolder, title),
  captureClipboard: () => ipcRenderer.invoke(CH.captureClipboard),

  getHotkey: () => ipcRenderer.invoke(CH.getHotkey),
  setHotkey: (accelerator) => ipcRenderer.invoke(CH.setHotkey, accelerator),
  showCommandBar: (mode) => ipcRenderer.send(CH.showCommandBar, mode ?? 'search'),
  hideCommandBar: () => ipcRenderer.send(CH.hideCommandBar),
  onCommandBarShow: (callback) => subscribe<'search' | 'capture'>(CH.commandBarShow, callback),
  focus: (target) => ipcRenderer.send(CH.focus, target),
  onFocus: (callback) => subscribe<FocusTarget>(CH.focusEvent, callback),
};

contextBridge.exposeInMainWorld('universe', bridge);
