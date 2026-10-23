// Labels appear only up close (SPEC §7): the nearest items in front of the camera get their titles, search
// results get their numbers (1–9, for "the second one"), and the item under the pointer gets a tooltip.
// Clicks go through the GPU picker: an item selects it, a double-click opens its viewer.
import type { ItemType } from '@universe/shared-types';
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import { Vector3 } from 'three';
import { ITEM_TYPES } from '../../lib/itemTypes';
import { useUniverse } from '../../state/store';
import { nearestInFront } from './helpers';
import { picker, useInteraction } from './interaction';
import { useLayout } from './layoutController';
import { useOverlay } from './overlay';
import { useScene } from './sceneData';
import { styleFor } from './types';

const PICK_INTERVAL_MS = 200;
const NUMBERED = 9;

function describe(index: number): string {
  const scene = useScene.getState().scene;
  const type = (scene.typeNames[index] ?? 'note') as ItemType;
  const body = styleFor(type, scene.ideaStages[index] ?? null).body;
  return `${ITEM_TYPES[type]?.label ?? type} · ${body}`;
}

export function ItemLabels({ count = 18, reach = 70 }: { count?: number; reach?: number }) {
  const { camera, size, gl } = useThree();
  const overlay = useOverlay();
  const pool = useRef<HTMLSpanElement[]>([]);
  const badges = useRef<HTMLSpanElement[]>([]);
  const tooltip = useRef<HTMLDivElement | null>(null);
  const chosen = useRef<number[]>([]);
  const lastPick = useRef(0);
  const lastCamera = useRef(new Vector3(Infinity, 0, 0));
  const forward = useRef(new Vector3());
  const results = useInteraction((s) => s.results);
  const hovered = useInteraction((s) => s.hovered);

  // Create the label elements once.
  useEffect(() => {
    const layer = overlay?.current;
    if (!layer) return;
    const make = (cls: string) => {
      const el = document.createElement('span');
      el.className = cls;
      el.style.visibility = 'hidden';
      layer.appendChild(el);
      return el;
    };
    pool.current = Array.from({ length: count }, () =>
      make('universe-label absolute top-0 left-0 max-w-48 truncate text-[11px] text-ink-2'),
    );
    badges.current = Array.from({ length: NUMBERED }, (_, k) => {
      const el = make(
        'universe-badge absolute top-0 left-0 grid size-5 place-items-center rounded-full font-mono text-[11px]',
      );
      el.textContent = String(k + 1);
      el.dataset.testid = 'result-badge';
      return el;
    });
    const tip = document.createElement('div');
    tip.className = 'glass-solid pointer-events-none absolute top-0 left-0 px-2 py-1 text-xs';
    tip.style.opacity = '0';
    tip.dataset.testid = 'universe-tooltip';
    layer.appendChild(tip);
    tooltip.current = tip;
    return () => {
      [...pool.current, ...badges.current, tip].forEach((el) => el.remove());
    };
  }, [overlay, count]);

  // Pointer: hover tooltip and click/double-click through the GPU picker.
  useEffect(() => {
    const el = gl.domElement;
    let down: { x: number; y: number } | null = null;
    let lastMove = 0;
    const local = (e: PointerEvent | MouseEvent) => {
      const rect = el.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };
    const onMove = (e: PointerEvent) => {
      const now = performance.now();
      if (now - lastMove < 60 || e.buttons) return;
      lastMove = now;
      const { x, y } = local(e);
      const index = picker.pick(x, y);
      useInteraction.getState().setHovered(index);
      el.style.cursor = index >= 0 ? 'pointer' : '';
      const tip = tooltip.current;
      if (tip) tip.style.transform = `translate(${x + 14}px, ${y + 12}px)`;
    };
    const onDown = (e: PointerEvent) => {
      down = local(e);
    };
    const onUp = (e: PointerEvent) => {
      const at = local(e);
      if (!down || Math.hypot(at.x - down.x, at.y - down.y) > 4) return;
      down = null;
      const index = picker.pick(at.x, at.y);
      const s = useUniverse.getState();
      if (index >= 0) {
        const id = useScene.getState().scene.ids[index];
        if (id) s.selectItem(id);
        return;
      }
      // Empty space: a galaxy under the pointer selects it, otherwise zoom out one level.
      const galaxy = galaxyAt(at.x, at.y);
      if (galaxy) s.selectProject(galaxy);
      else if (!s.viewerItemId) s.zoomOut();
    };
    const onDouble = (e: MouseEvent) => {
      const { x, y } = local(e);
      const index = picker.pick(x, y);
      const id = index >= 0 ? useScene.getState().scene.ids[index] : undefined;
      if (id) useUniverse.getState().openViewer(id);
      else {
        const galaxy = galaxyAt(x, y);
        if (galaxy) useUniverse.getState().openDashboard(galaxy);
      }
    };
    const onLeave = () => useInteraction.getState().setHovered(-1);
    const galaxyAt = (x: number, y: number): string | null => {
      const layout = useLayout.getState().current;
      const scene = useScene.getState().scene;
      if (!layout) return null;
      const v = new Vector3();
      let best: { id: string; d: number } | null = null;
      for (let g = 0; g < scene.galaxyIds.length; g++) {
        const c = layout.galaxyCentres;
        v.set(c[g * 3]!, c[g * 3 + 1]!, c[g * 3 + 2]!);
        const r = layout.galaxyRadii[g] ?? 8;
        const edge = v
          .clone()
          .add(new Vector3(r, 0, 0))
          .project(camera);
        v.project(camera);
        if (v.z > 1) continue;
        const sx = ((v.x + 1) / 2) * size.width;
        const sy = ((1 - v.y) / 2) * size.height;
        const sr = Math.abs(((edge.x + 1) / 2) * size.width - sx);
        const d = Math.hypot(x - sx, y - sy);
        if (d < Math.max(sr, 12) && (!best || d < best.d)) best = { id: scene.galaxyIds[g]!, d };
      }
      return best?.id ?? null;
    };
    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerdown', onDown);
    el.addEventListener('pointerup', onUp);
    el.addEventListener('dblclick', onDouble);
    el.addEventListener('pointerleave', onLeave);
    return () => {
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerdown', onDown);
      el.removeEventListener('pointerup', onUp);
      el.removeEventListener('dblclick', onDouble);
      el.removeEventListener('pointerleave', onLeave);
    };
  }, [gl, camera, size]);

  useEffect(() => {
    const tip = tooltip.current;
    if (!tip) return;
    const scene = useScene.getState().scene;
    if (hovered < 0 || hovered >= scene.n) {
      tip.style.opacity = '0';
      return;
    }
    tip.innerHTML = '';
    const title = document.createElement('div');
    title.className = 'text-ink-1';
    title.textContent = scene.titles[hovered] ?? '';
    const meta = document.createElement('div');
    meta.className = 'text-[11px] text-ink-3';
    meta.textContent = describe(hovered);
    tip.append(title, meta);
    tip.style.opacity = '1';
  }, [hovered]);

  const v = new Vector3();
  useFrame(() => {
    const layout = useLayout.getState().current;
    const scene = useScene.getState().scene;
    if (!layout || layout.positions.length !== scene.n * 3) return;
    const now = performance.now();
    if (
      now - lastPick.current > PICK_INTERVAL_MS &&
      lastCamera.current.distanceToSquared(camera.position) > 0.01
    ) {
      lastPick.current = now;
      lastCamera.current.copy(camera.position);
      camera.getWorldDirection(forward.current);
      chosen.current = nearestInFront(layout.positions, camera.position, forward.current, count, reach);
    }
    const place = (el: HTMLElement, index: number, text: string | null) => {
      const p = layout.positions;
      v.set(p[index * 3]!, p[index * 3 + 1]!, p[index * 3 + 2]!).project(camera);
      if (v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1) {
        el.style.visibility = 'hidden';
        return;
      }
      if (text !== null && el.textContent !== text) el.textContent = text;
      const x = ((v.x + 1) / 2) * size.width;
      const y = ((1 - v.y) / 2) * size.height;
      el.style.transform = `translate(${x + 8}px, ${y - 8}px)`;
      el.style.visibility = 'visible';
    };
    badges.current.forEach((el, k) => {
      const index = results[k];
      if (index === undefined || index >= scene.n) el.style.visibility = 'hidden';
      else place(el, index, null);
    });
    pool.current.forEach((el, k) => {
      const index = chosen.current[k];
      if (index === undefined || index >= scene.n) el.style.visibility = 'hidden';
      else place(el, index, scene.titles[index] ?? '');
    });
  });
  return null;
}
