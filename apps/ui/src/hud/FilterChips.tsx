// Filter chips under the search bar in the universe view (SPEC §7: type, project, date, tag). Types hide
// everything else in the universe; the galaxy chip is the current selection; date is the Time layout's
// slider; tags are searched with #tag in the query.
import { Clock, X } from 'lucide-react';
import { useProjects } from '../lib/queries';
import { TYPE_CHIPS } from '../lib/itemTypes';
import { useUniverse } from '../state/store';

export function FilterChips() {
  const typeFilter = useUniverse((s) => s.typeFilter);
  const setTypeFilter = useUniverse((s) => s.setTypeFilter);
  const selectedProject = useUniverse((s) => s.selectedProjectId);
  const selectProject = useUniverse((s) => s.selectProject);
  const layout = useUniverse((s) => s.layout);
  const setLayout = useUniverse((s) => s.setLayout);
  const projects = useProjects();
  const galaxy = projects.data?.find((p) => p.id === selectedProject);
  const chip = (active: boolean) =>
    `pointer-events-auto rounded-full border px-2.5 py-0.5 text-[11px] transition-colors duration-150 ${
      active
        ? 'border-accent/60 bg-accent/15 text-ink-1'
        : 'border-hairline-2 bg-space-1/70 text-ink-3 hover:text-ink-1'
    }`;
  return (
    <div
      role="toolbar"
      aria-label="Filters"
      className="absolute top-12 left-1/2 flex max-w-[calc(100vw-48rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-1.5"
      data-testid="filter-chips"
    >
      {TYPE_CHIPS.map((c) => {
        const active = c.types.every((t) => typeFilter.includes(t));
        return (
          <button
            key={c.label}
            type="button"
            aria-pressed={active}
            className={chip(active)}
            onClick={() =>
              setTypeFilter(
                active ? typeFilter.filter((t) => !c.types.includes(t)) : [...typeFilter, ...c.types],
              )
            }
          >
            {c.label}
          </button>
        );
      })}
      {typeFilter.length > 0 && (
        <button
          type="button"
          className={chip(false)}
          onClick={() => setTypeFilter([])}
          aria-label="Show every type"
        >
          <X className="inline size-3" aria-hidden /> All types
        </button>
      )}
      {galaxy && (
        <button
          type="button"
          className={chip(true)}
          onClick={() => selectProject(null)}
          aria-label={`Leave ${galaxy.name}`}
        >
          {galaxy.name} <X className="inline size-3" aria-hidden />
        </button>
      )}
      <button
        type="button"
        aria-pressed={layout === 'time'}
        className={chip(layout === 'time')}
        onClick={() => setLayout(layout === 'time' ? 'project' : 'time')}
        title="Time layout with the time-travel slider"
      >
        <Clock className="inline size-3" aria-hidden /> Date
      </button>
    </div>
  );
}
