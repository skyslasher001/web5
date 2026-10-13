// A galaxy's dashboard (SPEC §7: goals, tasks, status, timeline, linked items and agent reports).
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { tokens } from '@universe/design-tokens';
import type { ItemType, Project, ProjectGoal } from '@universe/shared-types';
import { Plus, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useApi } from '../../lib/api-context';
import { attempt } from '../../lib/attempt';
import { hueHex } from '../../lib/colors';
import { timeAgo } from '../../lib/format';
import { ITEM_TYPES } from '../../lib/itemTypes';
import { useUniverse } from '../../state/store';
import { useScene } from '../../universe/scene/sceneData';
import { Button, inputClass, SectionTitle } from '../ui';

const STATUSES = ['active', 'paused', 'done', 'archived'] as const;

function Goals({ project }: { project: Project }) {
  const api = useApi();
  const client = useQueryClient();
  const [text, setText] = useState('');
  const save = (goals: ProjectGoal[]) =>
    attempt(
      'Update goals',
      api
        .patchProject(project.id, { goals })
        .then(() => client.invalidateQueries({ queryKey: ['projects'] })),
    );
  return (
    <section className="space-y-2" data-testid="goals">
      <SectionTitle>Goals and tasks</SectionTitle>
      {project.goals.length === 0 && <p className="text-xs text-ink-3">None yet: add the first below.</p>}
      <ul className="space-y-1">
        {project.goals.map((g, k) => (
          <li key={`${k}-${g.text}`} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={g.done}
              aria-label={g.text}
              onChange={() => save(project.goals.map((x, j) => (j === k ? { ...x, done: !x.done } : x)))}
              className="accent-[var(--color-accent)]"
            />
            <span className={`flex-1 ${g.done ? 'text-ink-3 line-through' : 'text-ink-1'}`}>{g.text}</span>
            <button
              type="button"
              title="Remove"
              onClick={() => save(project.goals.filter((_, j) => j !== k))}
            >
              <X className="size-3.5 text-ink-3 hover:text-danger" aria-label="Remove" />
            </button>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && text.trim()) {
              save([...project.goals, { text: text.trim(), done: false }]);
              setText('');
            }
          }}
          placeholder="A goal or task"
          aria-label="New goal"
          className={`${inputClass} flex-1`}
        />
        <Button
          onClick={() => {
            if (!text.trim()) return;
            save([...project.goals, { text: text.trim(), done: false }]);
            setText('');
          }}
        >
          <Plus className="size-3.5" aria-hidden /> Add
        </Button>
      </div>
    </section>
  );
}

/** Items by type and per month over the last year, from the scene data (no extra request). */
function useGalaxyStats(projectId: string) {
  const scene = useScene((s) => s.scene);
  return useMemo(() => {
    const g = scene.galaxyIds.indexOf(projectId);
    const byType = new Map<string, number>();
    const months = new Array<number>(12).fill(0);
    const now = new Date();
    for (let i = 0; i < scene.n; i++) {
      if (scene.galaxy[i] !== g) continue;
      const type = scene.typeNames[i]!;
      byType.set(type, (byType.get(type) ?? 0) + 1);
      const d = new Date(scene.created[i]! * 1000);
      const age = (now.getFullYear() - d.getFullYear()) * 12 + now.getMonth() - d.getMonth();
      if (age >= 0 && age < 12) months[11 - age]!++;
    }
    return { byType: [...byType.entries()].sort((a, b) => b[1] - a[1]), months };
  }, [scene, projectId]);
}

export function ProjectDashboard({ project }: { project: Project }) {
  const api = useApi();
  const client = useQueryClient();
  const open = useUniverse((s) => s.openViewer);
  const selectTask = useUniverse((s) => s.selectTask);
  const stats = useGalaxyStats(project.id);
  const recent = useQuery({
    queryKey: ['items', 'dashboard', project.id],
    queryFn: () => api.items({ project: project.id, sort: 'added', limit: 8 }),
  });
  const reports = useQuery({
    queryKey: ['audit', 'linked', project.id],
    queryFn: () => api.audit(500, 'item.linked'),
    select: (entries) => entries.filter((e) => e.target_id === project.id).slice(0, 8),
  });
  const peak = Math.max(1, ...stats.months);
  return (
    <div className="grid h-full min-h-0 grid-cols-2 gap-6 overflow-y-auto" data-testid="dashboard">
      <div className="space-y-5">
        <div className="space-y-2">
          <p className="text-sm leading-relaxed text-ink-2">{project.description || 'No description.'}</p>
          <label className="flex items-center gap-2 text-xs text-ink-3">
            Status
            <select
              value={project.status}
              onChange={(e) =>
                attempt(
                  'Update status',
                  api
                    .patchProject(project.id, { status: e.target.value })
                    .then(() => client.invalidateQueries({ queryKey: ['projects'] })),
                )
              }
              className={inputClass}
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
        <Goals project={project} />
        <section className="space-y-2">
          <SectionTitle>Timeline (items added per month)</SectionTitle>
          <div
            className="flex h-16 items-end gap-1"
            role="img"
            aria-label="Items added per month over the last year"
          >
            {stats.months.map((m, k) => (
              <div
                key={k}
                className="flex-1 rounded-t-sm"
                style={{
                  height: `${(m / peak) * 100}%`,
                  minHeight: 2,
                  background: hueHex(project.color_token),
                }}
                title={`${m} items`}
              />
            ))}
          </div>
        </section>
      </div>
      <div className="space-y-5">
        <section className="space-y-2">
          <SectionTitle>Items ({project.item_count})</SectionTitle>
          <ul className="flex flex-wrap gap-1.5">
            {stats.byType.map(([type, count]) => {
              const style = ITEM_TYPES[type as ItemType];
              const Icon = style.Icon;
              return (
                <li
                  key={type}
                  className="flex items-center gap-1 rounded-full border border-hairline-2 px-2 py-0.5 text-[11px] text-ink-2"
                >
                  <Icon className="size-3" style={{ color: tokens.color[style.hue] }} aria-hidden />
                  {count} {count === 1 ? style.label : style.plural}
                </li>
              );
            })}
          </ul>
          <ul className="space-y-0.5 text-sm">
            {recent.data?.items.map((i) => (
              <li key={i.id}>
                <button
                  type="button"
                  onClick={() => open(i.id)}
                  className="w-full truncate text-left text-ink-2 hover:text-accent"
                >
                  {i.title} <span className="text-[11px] text-ink-3">· {timeAgo(i.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section className="space-y-2">
          <SectionTitle>Agent reports</SectionTitle>
          {reports.data && reports.data.length === 0 && (
            <p className="text-xs text-ink-3">No agent has linked anything here yet.</p>
          )}
          <ul className="space-y-1 text-xs">
            {reports.data?.map((e) => (
              <li key={e.seq} className="flex items-center gap-2 text-ink-2">
                <span className="flex-1">
                  {e.actor.replace(/^agent:/, '')} linked{' '}
                  {Array.isArray(e.details.items) ? e.details.items.length : 0} item(s) · {timeAgo(e.ts)}
                </span>
                {e.task_id && (
                  <button
                    type="button"
                    onClick={() => selectTask(e.task_id)}
                    className="text-ink-3 hover:text-accent"
                  >
                    Trace
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
