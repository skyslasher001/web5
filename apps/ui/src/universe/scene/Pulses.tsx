// Signal pulses (SPEC §7, §10 neural pathways): when you or an agent move from one item to another, a pulse
// of light travels the pathway between them, hop by hop along the links (`link.fired` events). Unlinked
// pairs get a fainter, direct pulse: that's the kind of firing the brain layer will turn into a suggested
// link. One draw call for every pulse; nothing moves with reduced motion.
import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  Points,
  PointsMaterial,
  Vector3,
} from 'three';
import { tokens } from '@universe/design-tokens';
import { hueHex } from '../../lib/colors';
import { onCoreEvent, useUniverse } from '../../state/store';
import { glowTexture } from '../textures';
import { HOP_MS, itemPosition, linkPath, pulseAt } from './helpers';
import { pulseStats, STILL } from './interaction';
import { useScene } from './sceneData';

const MAX = 48; // pulses in flight at once (the oldest gives way)
const TAIL = 6; // points per pulse: the head and a fading tail
const TAIL_MS = 40;

interface Pulse {
  route: Vector3[];
  start: number;
  color: Color;
  strength: number; // 1 along links, fainter for a direct (unlinked) jump
}

export function Pulses() {
  const pulses = useRef<Pulse[]>([]);
  const points = useRef<Points>(null);
  const scratch = useMemo(() => new Vector3(), []);
  const geometry = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new BufferAttribute(new Float32Array(MAX * TAIL * 3), 3));
    g.setAttribute('color', new BufferAttribute(new Float32Array(MAX * TAIL * 3), 3));
    return g;
  }, []);
  const material = useMemo(
    () =>
      new PointsMaterial({
        size: 2.4,
        map: glowTexture('#ffffff', 64),
        vertexColors: true,
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
      }),
    [],
  );
  useEffect(
    () => () => {
      geometry.dispose();
      material.map?.dispose();
      material.dispose();
    },
    [geometry, material],
  );

  useEffect(
    () =>
      onCoreEvent((event) => {
        if (event.type !== 'link.fired' || STILL) return;
        const p = event.payload as {
          from_id?: string;
          to_id?: string;
          link_id?: string | null;
          agent_id?: string;
        };
        const scene = useScene.getState().scene;
        const from = p.from_id ? scene.index.get(p.from_id) : undefined;
        const to = p.to_id ? scene.index.get(p.to_id) : undefined;
        if (from === undefined || to === undefined) return;
        const path = linkPath(scene, from, to) ?? [from, to];
        const route = path.map(itemPosition);
        if (route.some((v) => v === null)) return; // the layout is catching up with new data
        const agent = p.agent_id ? useUniverse.getState().agents.find((a) => a.id === p.agent_id) : undefined;
        pulses.current.push({
          route: route as Vector3[],
          start: performance.now(),
          color: new Color(agent ? hueHex(agent.color) : tokens.color.accent),
          strength: path.length > 2 || p.link_id ? 1 : 0.45,
        });
        if (pulses.current.length > MAX) pulses.current.shift();
        pulseStats.launched++;
      }),
    [],
  );

  useFrame(() => {
    const pts = points.current;
    if (!pts) return;
    const now = performance.now();
    pulses.current = pulses.current.filter(
      (p) => now - p.start < (p.route.length - 1) * HOP_MS + TAIL * TAIL_MS,
    );
    const pos = geometry.getAttribute('position') as BufferAttribute;
    const col = geometry.getAttribute('color') as BufferAttribute;
    let n = 0;
    for (const p of pulses.current) {
      for (let k = 0; k < TAIL; k++) {
        const at = pulseAt(p.route, now - p.start - k * TAIL_MS, scratch);
        if (!at) continue;
        const fade = p.strength * (1 - k / TAIL);
        pos.setXYZ(n, at.x, at.y, at.z);
        col.setXYZ(n, p.color.r * fade, p.color.g * fade, p.color.b * fade);
        n++;
      }
    }
    geometry.setDrawRange(0, n);
    pos.needsUpdate = true;
    col.needsUpdate = true;
  });

  return <points ref={points} geometry={geometry} material={material} frustumCulled={false} />;
}
