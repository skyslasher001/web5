import { tokens } from '@universe/design-tokens';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useProjects } from '../lib/queries';
import { timeAgo } from '../lib/format';
import { useUniverse } from '../state/store';
import { Dot } from './ui';

const TONE = {
  info: tokens.color.slate,
  good: tokens.color.green,
  warn: tokens.color.amber,
  bad: tokens.color.danger,
};

export function ActivityRibbon() {
  const activity = useUniverse((s) => s.activity);
  const selected = useUniverse((s) => s.selectedProjectId);
  const projects = useProjects();
  const [open, setOpen] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, []);
  const galaxy = projects.data?.find((p) => p.id === selected);
  return (
    <section aria-label="Activity" className="pointer-events-auto absolute bottom-4 left-4 w-80">
      <div className="glass p-3">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex w-full items-center justify-between px-1 font-display text-[11px] font-semibold tracking-[0.14em] text-ink-3 uppercase"
          aria-expanded={open}
        >
          Activity
          {open ? (
            <ChevronDown className="size-3.5" aria-hidden />
          ) : (
            <ChevronUp className="size-3.5" aria-hidden />
          )}
        </button>
        {open && (
          <ol className="mt-2 max-h-44 space-y-1.5 overflow-y-auto px-1" data-testid="activity">
            {activity.length === 0 && <li className="text-xs text-ink-3">Nothing yet.</li>}
            {activity.slice(0, 12).map((item) => (
              <li key={item.id} className="flex items-start gap-2 text-xs">
                <span className="mt-1">
                  <Dot color={TONE[item.tone]} />
                </span>
                <span className="flex-1 text-ink-2">{item.text}</span>
                <time className="shrink-0 text-ink-3" dateTime={item.ts}>
                  {timeAgo(item.ts, now)}
                </time>
              </li>
            ))}
          </ol>
        )}
      </div>
      <nav aria-label="Breadcrumb" className="mt-2 px-2 text-xs text-ink-3">
        Universe{galaxy ? <span className="text-ink-2"> › {galaxy.name}</span> : null}
      </nav>
    </section>
  );
}
