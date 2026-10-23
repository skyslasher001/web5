// A ring around the selected item, so you can find it again after the camera moves.
import { tokens } from '@universe/design-tokens';
import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import { AdditiveBlending, CanvasTexture, SRGBColorSpace, type Sprite } from 'three';
import { useUniverse } from '../../state/store';
import { itemPosition } from './helpers';
import { STILL } from './interaction';
import { useScene } from './sceneData';

function ringTexture(color: string): CanvasTexture {
  const size = 128;
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d')!;
  ctx.strokeStyle = color;
  ctx.lineWidth = 5;
  ctx.shadowColor = color;
  ctx.shadowBlur = 12;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size * 0.38, 0, Math.PI * 2);
  ctx.stroke();
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

export function SelectionRing() {
  const ref = useRef<Sprite>(null);
  const selected = useUniverse((s) => s.selectedItemId);
  const texture = useMemo(() => ringTexture(tokens.color.accent), []);
  useFrame(({ camera, clock }) => {
    const sprite = ref.current;
    if (!sprite) return;
    const index = selected ? useScene.getState().scene.index.get(selected) : undefined;
    const p = index === undefined ? null : itemPosition(index);
    sprite.visible = p !== null;
    if (!p) return;
    sprite.position.copy(p);
    const d = camera.position.distanceTo(p);
    const pulse = STILL ? 1 : 1 + Math.sin(clock.elapsedTime * 3) * 0.06;
    sprite.scale.setScalar(Math.max(2.5, d * 0.06) * pulse);
  });
  return (
    <sprite ref={ref} visible={false}>
      <spriteMaterial
        map={texture}
        blending={AdditiveBlending}
        depthWrite={false}
        depthTest={false}
        transparent
      />
    </sprite>
  );
}
