// Connections as light filaments (SPEC §7): dashed = suggested. The Graph layout shows them all; other
// layouts show only the selected item's, so 14k lines never clutter the view.
import { tokens } from '@universe/design-tokens';
import { useEffect, useRef } from 'react';
import { AdditiveBlending, BufferAttribute, type LineBasicMaterial, type LineSegments } from 'three';
import { useUniverse } from '../../state/store';
import { linkSegments } from './helpers';
import { useLayout } from './layoutController';
import { useScene } from './sceneData';

export function Filaments() {
  const layout = useLayout((s) => s.current);
  const version = useScene((s) => s.version);
  const selected = useUniverse((s) => s.selectedItemId);
  const solid = useRef<LineSegments>(null);
  const dashed = useRef<LineSegments>(null);

  useEffect(() => {
    const scene = useScene.getState().scene;
    if (!layout || layout.positions.length !== scene.n * 3) return;
    const focus = selected ? scene.index.get(selected) : undefined;
    const all = layout.kind === 'graph';
    const touches = (k: number) =>
      focus !== undefined && (scene.linksA[k] === focus || scene.linksB[k] === focus);
    for (const [ref, suggested] of [
      [solid, 0],
      [dashed, 1],
    ] as const) {
      const line = ref.current;
      if (!line) continue;
      const keep = (k: number) => scene.linkSuggested[k] === suggested && (all || touches(k));
      line.geometry.setAttribute(
        'position',
        new BufferAttribute(linkSegments(layout.positions, scene.linksA, scene.linksB, keep), 3),
      );
      line.geometry.computeBoundingSphere();
      if (suggested) line.computeLineDistances();
      (line.material as LineBasicMaterial).opacity = all && focus === undefined ? 0.07 : 0.55;
    }
  }, [layout, version, selected]);

  return (
    <>
      <lineSegments ref={solid}>
        <bufferGeometry />
        <lineBasicMaterial
          color={tokens.color.cyan}
          transparent
          opacity={0.35}
          blending={AdditiveBlending}
          depthWrite={false}
        />
      </lineSegments>
      <lineSegments ref={dashed}>
        <bufferGeometry />
        <lineDashedMaterial
          color={tokens.color.violet}
          dashSize={1.2}
          gapSize={1}
          transparent
          opacity={0.4}
          blending={AdditiveBlending}
          depthWrite={false}
        />
      </lineSegments>
    </>
  );
}
