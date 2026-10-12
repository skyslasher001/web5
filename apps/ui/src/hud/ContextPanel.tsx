import { Sparkles } from 'lucide-react';
import { hueHex } from '../lib/colors';
import { useProjects } from '../lib/queries';
import { useUniverse } from '../state/store';
import { Dot, SectionTitle } from './ui';

export function ContextPanel() {
  const projects = useProjects();
  const selected = useUniverse((s) => s.selectedProjectId);
  const select = useUniverse((s) => s.selectProject);
  const galaxy = projects.data?.find((p) => p.id === selected);

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
            <dd className="mt-1 font-mono">0</dd>
          </div>
          <div className="rounded-md border border-hairline-1 p-3">
            <dt className="text-xs text-ink-3">Status</dt>
            <dd className="mt-1 capitalize">{galaxy.status}</dd>
          </div>
        </dl>
        <p className="flex gap-2 rounded-md border border-hairline-1 p-3 text-xs leading-relaxed text-ink-3">
          <Sparkles className="mt-0.5 size-3.5 shrink-0 text-accent-2" aria-hidden />
          Files, notes and songs land here when the vault arrives (Phase 2). Drop zones, previews and AI
          summaries will fill this panel.
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
              <span>
                <span className="block text-sm text-ink-1">{p.name}</span>
                <span className="block text-xs text-ink-3">{p.description}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
