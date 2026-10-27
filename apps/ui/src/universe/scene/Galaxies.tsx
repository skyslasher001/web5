// Galaxies (projects) as glowing spiral sprites: size from item count, brightness from recent activity
// (SPEC §7). Their names sit in the DOM overlay and fade as you fly into a galaxy.
import { tokens } from '@universe/design-tokens';
import type { Project } from '@universe/shared-types';
import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import { AdditiveBlending, Vector3, type Sprite } from 'three';
import { hueHex } from '../../lib/colors';
import { useProjects } from '../../lib/queries';
import { useUniverse } from '../../state/store';
import { STILL } from './interaction';
import { useLayout } from './layoutController';
import { useOverlay } from './overlay';
import { galaxyActivity } from './helpers';
import { useScene } from './sceneData';
import { galaxyTexture } from '../textures';

const scratch = new Vector3();

function GalaxySprite({ project, index }: { project: Project; index: number }) {
  const ref = useRef<Sprite>(null);
  const overlay = useOverlay();
  const label = useRef<HTMLSpanElement | null>(null);
  const layout = useLayout((s) => s.current);
  const scene = useScene((s) => s.scene);
  const selected = useUniverse((s) => s.selectedProjectId === project.id);
  const color = hueHex(project.color_token);
  const texture = useMemo(() => galaxyTexture(color, project.layout_seed + 1), [color, project.layout_seed]);
  const activity = useMemo(() => galaxyActivity(scene)[index] ?? 0, [scene, index]);

  useFrame(({ camera, size }, delta) => {
    const sprite = ref.current;
    if (!sprite || !layout || index * 3 + 2 >= layout.galaxyCentres.length) return;
    const c = layout.galaxyCentres;
    sprite.position.set(c[index * 3]!, c[index * 3 + 1]!, c[index * 3 + 2]!);
    const radius = layout.galaxyRadii[index] ?? 8;
    // Only the Project layout groups items into discs; elsewhere a galaxy is just a name over its members.
    const grouped = layout.kind === 'project';
    sprite.visible = grouped;
    const scale = radius * 2.1;
    sprite.scale.set(scale, scale, 1);
    if (!STILL) sprite.material.rotation += delta * 0.02;
    // Fade as the camera enters the galaxy, so its stars show through.
    const distance = camera.position.distanceTo(sprite.position);
    const near = Math.min(1, Math.max(0, (distance - radius * 0.8) / (radius * 2.5)));
    const base = 0.32 + Math.min(0.5, activity * 2);
    sprite.material.opacity = (selected ? 1 : base) * (0.12 + 0.88 * near);

    if (!label.current?.isConnected) {
      label.current =
        overlay?.current?.querySelector<HTMLSpanElement>(`[data-galaxy="${project.id}"]`) ?? null;
    }
    const el = label.current;
    if (el) {
      scratch.copy(sprite.position);
      scratch.y -= radius * (grouped ? 0.75 : 0.5);
      scratch.project(camera);
      const x = ((scratch.x + 1) / 2) * size.width;
      const y = ((1 - scratch.y) / 2) * size.height;
      el.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px)`;
      // Outside the Project layout a galaxy's members are spread out: only the selected one is named.
      const shown = scratch.z < 1 && (grouped || selected);
      el.style.opacity = shown ? String(0.35 + 0.65 * near) : '0';
    }
  });

  return (
    <sprite ref={ref}>
      <spriteMaterial map={texture} blending={AdditiveBlending} depthWrite={false} transparent />
    </sprite>
  );
}

export function Galaxies() {
  const projects = useProjects();
  const galaxyIds = useScene((s) => s.scene.galaxyIds);
  const byId = new Map((projects.data ?? []).map((p) => [p.id, p]));
  return (
    <>
      {galaxyIds.map((id, index) => {
        const project = byId.get(id);
        return project ? <GalaxySprite key={id} project={project} index={index} /> : null;
      })}
    </>
  );
}

/** Galaxy names in the DOM overlay (positioned by each sprite every frame). */
export function GalaxyLabels() {
  const projects = useProjects();
  const selected = useUniverse((s) => s.selectedProjectId);
  return (
    <>
      {(projects.data ?? []).map((p) => (
        <span
          key={p.id}
          data-galaxy={p.id}
          className="absolute top-0 left-0 font-display text-xs whitespace-nowrap"
          style={{
            color: selected === p.id ? tokens.color.ink['1'] : tokens.color.ink['2'],
            letterSpacing: '0.06em',
            opacity: 0,
            textShadow: `0 0 8px ${tokens.color.space['0']}`,
          }}
        >
          {p.name}
          <span className="ml-1.5 font-mono text-[10px] text-ink-3">{p.item_count}</span>
        </span>
      ))}
    </>
  );
}
