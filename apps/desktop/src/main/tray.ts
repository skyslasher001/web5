// Tray icon (SPEC §6: quick capture and quick search from the tray).
import { Menu, Tray, nativeImage, type MenuItemConstructorOptions, type NativeImage } from 'electron';
import { ringPixels } from './trayPixels';

function icon(): NativeImage {
  const image = nativeImage.createFromBitmap(ringPixels(32), { width: 32, height: 32 });
  return image.resize({ width: 16, height: 16 });
}

export function createTray(actions: {
  search: () => void;
  capture: () => void;
  captureClipboard: () => void;
  show: () => void;
  quit: () => void;
  hotkey: () => string;
  /** More items (the kill switch), rebuilt each time the menu opens. */
  extraItems?: () => MenuItemConstructorOptions[];
}): Tray {
  const tray = new Tray(icon());
  tray.setToolTip('UNIVERSE');
  const rebuild = () =>
    tray.setContextMenu(
      Menu.buildFromTemplate([
        {
          label: 'Quick search',
          // Shown next to the item; the global shortcut itself is registered by the command bar.
          ...(actions.hotkey() ? { accelerator: actions.hotkey(), registerAccelerator: false } : {}),
          click: actions.search,
        },
        { label: 'Quick capture', click: actions.capture },
        { label: 'Save clipboard to inbox', click: actions.captureClipboard },
        { type: 'separator' },
        ...(actions.extraItems?.() ?? []),
        { label: 'Show UNIVERSE', click: actions.show },
        { type: 'separator' },
        { label: 'Quit', click: actions.quit },
      ]),
    );
  rebuild();
  tray.on('click', actions.show);
  tray.on('right-click', rebuild);
  return tray;
}
