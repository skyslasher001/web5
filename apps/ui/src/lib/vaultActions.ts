// Item actions shared by the 2D views, the context panel, the palette and the command bar.
import { useUniverse } from '../state/store';
import { ApiError, type CoreApi } from './api';
import { attempt } from './attempt';
import { bridge } from './bridge';

/** Open with the default app: Core records the open, Electron main opens the file (vault paths only). */
export function openItem(api: CoreApi, id: string): void {
  attempt(
    'Open',
    api.openItem(id).then(async (opened) => {
      const error = await bridge().openPath(opened.abs_path);
      if (error) throw new Error(error);
    }),
  );
}

export function revealItem(api: CoreApi, id: string): void {
  attempt(
    'Show in folder',
    api.openItem(id).then(async (opened) => {
      if (!(await bridge().revealPath(opened.abs_path))) throw new Error('not inside the vault');
    }),
  );
}

export function trashItem(api: CoreApi, id: string, title: string): void {
  attempt(
    'Move to trash',
    api.deleteItem(id).then(() => {
      const s = useUniverse.getState();
      if (s.selectedItemId === id) s.selectItem(null);
      s.addNotice('info', `Moved “${title}” to the trash (kept 30 days)`);
      s.refreshItems();
    }),
  );
}

/** Files dropped on the window: Core copies them into the vault (sources are never moved or changed). */
export async function ingestDropped(api: CoreApi, files: File[], projectId: string | null): Promise<void> {
  const paths = bridge().pathsForFiles(files);
  const s = useUniverse.getState();
  if (paths.length === 0) {
    s.addNotice('warn', 'Nothing to add: drop files or folders from your computer');
    return;
  }
  try {
    const result = await api.ingestPaths(paths, projectId);
    const rejected = result.rejected.length ? ` · ${result.rejected.length} skipped` : '';
    s.addNotice(
      'good',
      `Adding ${result.queued} ${result.queued === 1 ? 'item' : 'items'} to the vault${rejected}`,
    );
    for (const r of result.rejected.slice(0, 3)) s.addNotice('warn', `Skipped ${r.path}: ${r.reason}`);
  } catch (err) {
    s.addNotice('bad', `Adding files failed: ${err instanceof ApiError ? err.message : String(err)}`);
  }
}
