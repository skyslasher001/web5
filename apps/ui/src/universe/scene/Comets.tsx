// Inbox captures arrive as comets (SPEC §7): a tail streams outward from each head, away from the Core,
// while the item waits at the edge for triage.
import { tokens } from '@universe/design-tokens';
import { useEffect, useRef } from 'react';
import { AdditiveBlending, BufferAttribute, Color, type LineSegments } from 'three';
import { useLayout } from './layoutController';
import { useScene } from './sceneData';

const TAIL = 9;

export function Comets() {
  const layout = useLayout((s) => s.current);
  const version = useScene((s) => s.version);
  const line = useRef<LineSegments>(null);
  useEffect(() => {
    const scene = useScene.getState().scene;
    const l = line.current;
    if (!l || !layout || layout.positions.length !== scene.n * 3) return;
    // Comets wait at the edge of the Project layout; elsewhere an inbox item is placed like any other.
    l.visible = layout.kind === 'project';
    const head = new Color(tokens.color.cyan);
    const positions: number[] = [];
    const colors: number[] = [];
    const p = layout.positions;
    for (let i = 0; i < scene.n; i++) {
      if (!scene.comet[i]) continue;
      const [x, y, z] = [p[i * 3]!, p[i * 3 + 1]!, p[i * 3 + 2]!];
      const len = Math.hypot(x, y, z) || 1;
      positions.push(x, y, z, x + (x / len) * TAIL, y + (y / len) * TAIL, z + (z / len) * TAIL);
      colors.push(head.r, head.g, head.b, 0, 0, 0); // additive: black fades the tail out
    }
    l.geometry.setAttribute('position', new BufferAttribute(new Float32Array(positions), 3));
    l.geometry.setAttribute('color', new BufferAttribute(new Float32Array(colors), 3));
    l.geometry.computeBoundingSphere();
  }, [layout, version]);
  return (
    <lineSegments ref={line}>
      <bufferGeometry />
      <lineBasicMaterial vertexColors transparent blending={AdditiveBlending} depthWrite={false} />
    </lineSegments>
  );
}
