import { Grid2x2, LayoutDashboard, Upload } from 'lucide-react';
import { hueHex } from '../lib/colors';
import { useProjects } from '../lib/queries';
import { useUniverse } from '../state/store';
import { ItemPanel } from './ItemPanel';
import { Dot, SectionTitle } from './ui';

export function ContextPanel() {
  const projects = useProjects();
  const selected = useUniverse((s) => s.selectedProjectId);
  const selectedItem = useUniverse((s) => s.selectedItemId);
  const select = useUniverse((s) => s.selectProject);
  const setView = useUniverse((s) => s.setView);
  const view = useUniverse((s) => s.view);
  const galaxy = projects.data?.find((p) => p.id === selected);

  if (selectedItem) return <ItemPanel id={selectedItem} />;

  if (galaxy) {
    return (
      <div className="space-y-5" data-testid="context-galaxy">
        <div>
          <p className="text-xs text-ink-3">Galaxy</p>
          <h2 className="mt-1 flex items-center gap-2 font-display text-xl font-semibold">
            <Dot color={hueHex(galaxy.color_token)} />
            {galaxy.name}
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">{galaxy.description}</p>
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-md border border-hairline-1 p-3">
            <dt className="text-xs text-ink-3">Items</dt>
            <dd className="mt-1 font-mono" data-testid="galaxy-item-count">
              {galaxy.item_count}
            </dd>
          </div>
          <div className="rounded-md border border-hairline-1 p-3">
            <dt className="text-xs text-ink-3">Status</dt>
            <dd className="mt-1 capitalize">{galaxy.status}</dd>
          </div>
        </dl>
        <button
          type="button"
          onClick={() => useUniverse.getState().openDashboard(galaxy.id)}
          className="flex items-center gap-2 rounded-md border border-hairline-2 px-3 py-1.5 text-xs text-ink-2 hover:border-accent/60"
          data-testid="open-dashboard"
        >
          <LayoutDashboard className="size-3.5" aria-hidden /> Dashboard
        </button>
        {view === 'universe' && (
          <button
            type="button"
            onClick={() => setView('grid')}
            className="flex items-center gap-2 rounded-md border border-hairline-2 px-3 py-1.5 text-xs text-ink-2 hover:border-accent/60"
          >
            <Grid2x2 className="size-3.5" aria-hidden /> Show its items
          </button>
        )}
        <p className="flex gap-2 rounded-md border border-hairline-1 p-3 text-xs leading-relaxed text-ink-3">
          <Upload className="mt-0.5 size-3.5 shrink-0 text-accent-2" aria-hidden />
          Files you drop while this galaxy is selected join it. Items can belong to several galaxies.
        </p>
        <button type="button" onClick={() => select(null)} className="text-xs text-ink-3 hover:text-ink-2">
          ← All galaxies
        </button>
      </div>
    );
  }

  return (
    <div>
      <SectionTitle>Galaxies</SectionTitle>
      <p className="mb-3 text-xs text-ink-3">Select one here or in the universe.</p>
      <ul className="space-y-1" data-testid="galaxy-list">
        {projects.data?.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              onClick={() => select(p.id)}
              className="flex w-full items-start gap-3 rounded-md px-2 py-2 text-left transition-colors duration-150 hover:bg-space-3/60"
            >
              <span className="mt-1.5">
                <Dot color={hueHex(p.color_token)} />
              </span>
              <span className="flex-1">
                <span className="block text-sm text-ink-1">{p.name}</span>
                <span className="block text-xs text-ink-3">{p.description}</span>
              </span>
              <span className="font-mono text-xs text-ink-3">{p.item_count}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
