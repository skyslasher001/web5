// Bottom left (SPEC §7): minimap and breadcrumb (Universe › Ember Wolf › Note), the zoom level, the four
// layouts (keys 1–4) and, in the Time layout, the time-travel slider. A live region tells screen readers
// what changed.
import { tokens } from '@universe/design-tokens';
import type { ItemType } from '@universe/shared-types';
import { Pause, Play } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Vector3 } from 'three';
import { hueHex } from '../lib/colors';
import { ITEM_TYPES } from '../lib/itemTypes';
import { useProjects } from '../lib/queries';
import { LAYOUTS, useUniverse, type Layout } from '../state/store';
import { rig, zoomLevel } from '../universe/scene/helpers';
import { useInteraction } from '../universe/scene/interaction';
import { useLayout } from '../universe/scene/layoutController';
import { useScene } from '../universe/scene/sceneData';
import { styleFor } from '../universe/scene/types';
import { Kbd } from './ui';

const LAYOUT_LABEL: Record<Layout, string> = {
  project: 'Project',
  semantic: 'Semantic',
  time: 'Time',
  graph: 'Graph',
};

function Minimap() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const projects = useProjects();
  useEffect(() => {
    const draw = () => {
      const c = canvas.current;
      const ctx = c?.getContext('2d');
      const layout = useLayout.getState().current;
      if (!c || !ctx || !layout) return;
      const scene = useScene.getState().scene;
      const w = c.width;
      const h = c.height;
      const scale = (Math.min(w, h) / 2 - 6) / Math.max(layout.extent * 0.85, 1);
      const sx = (x: number) => w / 2 + x * scale;
      const sy = (z: number) => h / 2 + z * scale;
      ctx.clearRect(0, 0, w, h);
      const byId = new Map((projects.data ?? []).map((p) => [p.id, p]));
      scene.galaxyIds.forEach((id, g) => {
        const project = byId.get(id);
        if (!project || g * 3 + 2 >= layout.galaxyCentres.length) return;
        ctx.fillStyle = hueHex(project.color_token);
        ctx.globalAlpha = 0.75;
        ctx.beginPath();
        ctx.arc(
          sx(layout.galaxyCentres[g * 3]!),
          sy(layout.galaxyCentres[g * 3 + 2]!),
          Math.max(1.5, (layout.galaxyRadii[g] ?? 6) * scale),
          0,
          Math.PI * 2,
        );
        ctx.fill();
      });
      ctx.globalAlpha = 1;
      ctx.fillStyle = tokens.color.accent;
      ctx.fillRect(w / 2 - 1.5, h / 2 - 1.5, 3, 3); // the Core
      const { position, target } = rig.state();
      const [px, , pz] = position as [number, number, number];
      const [tx, , tz] = target as [number, number, number];
      ctx.strokeStyle = tokens.color.ink['1'];
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(sx(px), sy(pz));
      ctx.lineTo(sx(tx), sy(tz));
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(sx(px), sy(pz), 2.5, 0, Math.PI * 2);
      ctx.fillStyle = tokens.color.ink['1'];
      ctx.fill();
    };
    const timer = setInterval(draw, 300);
    draw();
    return () => clearInterval(timer);
  }, [projects.data]);
  return (
    <canvas
      ref={canvas}
      width={168}
      height={96}
      className="w-full cursor-pointer rounded-md bg-space-1/60"
      aria-label="Minimap: click to fly there"
      data-testid="minimap"
      onClick={(e) => {
        const layout = useLayout.getState().current;
        const c = canvas.current;
        if (!layout || !c) return;
        const rect = c.getBoundingClientRect();
        const scale = (Math.min(c.width, c.height) / 2 - 6) / Math.max(layout.extent * 0.85, 1);
        const x = ((e.clientX - rect.left) * (c.width / rect.width) - c.width / 2) / scale;
        const z = ((e.clientY - rect.top) * (c.height / rect.height) - c.height / 2) / scale;
        rig.flyTo(new Vector3(x, 0, z), layout.extent * 0.4);
      }}
    />
  );
}

function TimeSlider() {
  const timeCut = useUniverse((s) => s.timeCut);
  const setTimeCut = useUniverse((s) => s.setTimeCut);
  const scene = useScene((s) => s.scene);
  const [playing, setPlaying] = useState(false);
  const range = useMemo<[number, number]>(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const t of scene.created) {
      if (t < min) min = t;
      if (t > max) max = t;
    }
    return Number.isFinite(min) ? [min, max] : [0, 0];
  }, [scene]);
  // Replay the universe growing, oldest item to newest, in about 15 seconds.
  useEffect(() => {
    if (!playing) return;
    const [min, max] = range;
    const started = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / 15_000);
      setTimeCut(t >= 1 ? null : min + (max - min) * t);
      if (t < 1) raf = requestAnimationFrame(tick);
      else setPlaying(false);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, range, setTimeCut]);
  const [min, max] = range;
  const value = timeCut ?? max;
  return (
    <div className="space-y-1" data-testid="time-slider">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setPlaying(!playing)}
          aria-label={playing ? 'Pause the replay' : 'Replay the universe growing'}
          className="text-ink-2 hover:text-accent"
        >
          {playing ? <Pause className="size-3.5" aria-hidden /> : <Play className="size-3.5" aria-hidden />}
        </button>
        <input
          type="range"
          min={min}
          max={max}
          step={Math.max(1, (max - min) / 400)}
          value={value}
          onChange={(e) => {
            setPlaying(false);
            const v = Number(e.target.value);
            setTimeCut(v >= max ? null : v);
          }}
          aria-label="Time travel: show the universe as it was on"
          className="flex-1 accent-[var(--color-accent)]"
        />
      </div>
      <p className="font-mono text-[11px] text-ink-3">
        {timeCut === null ? 'Now' : new Date(value * 1000).toLocaleDateString()}
      </p>
    </div>
  );
}

function Announcer() {
  const selected = useUniverse((s) => s.selectedItemId);
  const layout = useUniverse((s) => s.layout);
  const results = useInteraction((s) => s.results);
  const scene = useScene((s) => s.scene);
  // The newest thing worth saying: results, then the selection, then the layout.
  let text = `${LAYOUT_LABEL[layout]} layout`;
  const i = selected ? scene.index.get(selected) : undefined;
  if (results.length) text = `${results.length} results, numbered from the closest match`;
  else if (i !== undefined) {
    const type = scene.typeNames[i] as ItemType;
    text = `Selected ${scene.titles[i]}, ${ITEM_TYPES[type]?.label ?? type}, a ${styleFor(type, scene.ideaStages[i] ?? null).body}`;
  }
  return (
    <p className="sr-only" aria-live="polite">
      {text}
    </p>
  );
}

export function NavigatorCard() {
  const s = useUniverse();
  const projects = useProjects();
  const notice = useLayout((l) => l.notice);
  const computing = useLayout((l) => l.computing);
  const quality = useUniverse((st) => st.quality);
  const scene = useScene((st) => st.scene);
  const level = zoomLevel(s);
  const itemIndex = s.selectedItemId ? scene.index.get(s.selectedItemId) : undefined;
  const galaxyId =
    s.selectedProjectId ?? (itemIndex !== undefined ? scene.galaxyIds[scene.galaxy[itemIndex]!] : undefined);
  const galaxy = projects.data?.find((p) => p.id === galaxyId);
  const crumb = (label: string, onClick?: () => void) =>
    onClick ? (
      <button type="button" onClick={onClick} className="hover:text-accent">
        {label}
      </button>
    ) : (
      <span className="text-ink-1">{label}</span>
    );
  return (
    <section
      aria-label="Navigator"
      className="glass pointer-events-auto space-y-2 p-3"
      data-testid="navigator"
    >
      {quality !== 'lite' && <Minimap />}
      <nav
        aria-label="Breadcrumb"
        className="flex flex-wrap items-center gap-1 text-xs text-ink-3"
        data-testid="breadcrumb"
      >
        {crumb('Universe', galaxy || itemIndex !== undefined ? () => s.flyHome() : undefined)}
        {galaxy && (
          <>
            <span aria-hidden>›</span>
            {crumb(galaxy.name, itemIndex !== undefined ? () => s.selectProject(galaxy.id) : undefined)}
          </>
        )}
        {itemIndex !== undefined && (
          <>
            <span aria-hidden>›</span>
            <span className="max-w-32 truncate text-ink-1">{scene.titles[itemIndex]}</span>
          </>
        )}
      </nav>
      <div className="flex items-center justify-between gap-2">
        <span
          className="font-display text-[11px] tracking-[0.12em] text-ink-3 uppercase"
          data-testid="zoom-level"
        >
          {level}
        </span>
        <div role="radiogroup" aria-label="Layout" className="flex gap-1">
          {LAYOUTS.map((l, k) => (
            <button
              key={l}
              type="button"
              role="radio"
              aria-checked={s.layout === l}
              title={`${LAYOUT_LABEL[l]} layout (${k + 1})`}
              onClick={() => s.setLayout(l)}
              className={`rounded-sm px-1.5 py-0.5 text-[11px] ${
                s.layout === l ? 'bg-space-3 text-ink-1' : 'text-ink-3 hover:text-ink-2'
              }`}
              data-testid={`layout-${l}`}
            >
              {LAYOUT_LABEL[l]}
            </button>
          ))}
        </div>
      </div>
      {(notice || computing) && (
        <p className="text-[11px] leading-relaxed text-ink-3" data-testid="layout-notice">
          {notice ?? `Arranging the ${LAYOUT_LABEL[computing!]} layout…`}
        </p>
      )}
      {s.layout === 'time' && <TimeSlider />}
      <p className="text-[11px] text-ink-3">
        <Kbd>H</Kbd> home · <Kbd>Esc</Kbd> back · <Kbd>1</Kbd>–<Kbd>4</Kbd> layouts
      </p>
      <Announcer />
    </section>
  );
}
