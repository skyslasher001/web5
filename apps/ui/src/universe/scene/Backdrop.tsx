// The backdrop: a slow parallax starfield far beyond the data, and the Core (home star) at the centre,
// pulsing with system activity (SPEC §7).
import { tokens } from '@universe/design-tokens';
import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import { AdditiveBlending, BufferAttribute, BufferGeometry, Color, type Points, type Sprite } from 'three';
import { useUniverse } from '../../state/store';
import { glowTexture } from '../textures';
import { mulberry32 } from './helpers';
import { STILL } from './interaction';

export function Starfield({ count = 4000 }: { count?: number }) {
  const ref = useRef<Points>(null);
  const geometry = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const random = mulberry32(20261012);
    const palette = [
      tokens.color.ink['1'],
      tokens.color.ink['2'],
      tokens.color.cyan,
      tokens.color.violet,
    ].map((c) => new Color(c));
    for (let i = 0; i < count; i++) {
      const r = 2500 + random() * 3500;
      const theta = random() * Math.PI * 2;
      const phi = Math.acos(2 * random() - 1);
      positions.set(
        [r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta)],
        i * 3,
      );
      const c = palette[random() < 0.82 ? Math.floor(random() * 2) : 2 + Math.floor(random() * 2)]!;
      colors.set([c.r * 0.7, c.g * 0.7, c.b * 0.7], i * 3);
    }
    const g = new BufferGeometry();
    g.setAttribute('position', new BufferAttribute(positions, 3));
    g.setAttribute('color', new BufferAttribute(colors, 3));
    return g;
  }, [count]);
  useFrame(({ camera }, delta) => {
    const points = ref.current;
    if (!points) return;
    points.position.copy(camera.position); // always far away: parallax from rotation only
    if (!STILL) points.rotation.y += delta * 0.004;
  });
  return (
    <points ref={ref} name="starfield" geometry={geometry} frustumCulled={false}>
      <pointsMaterial
        size={1.2}
        sizeAttenuation={false}
        vertexColors
        transparent
        opacity={0.85}
        depthWrite={false}
      />
    </points>
  );
}

export function CoreStar() {
  const ref = useRef<Sprite>(null);
  const activity = useUniverse((s) => s.agentActivity.core ?? 'idle');
  const online = useUniverse((s) => s.connection === 'online');
  const killed = useUniverse((s) => s.killSwitch.engaged);
  const texture = useMemo(() => glowTexture(tokens.color.accent), []);
  useFrame(({ clock }) => {
    if (!ref.current) return;
    const busy = activity === 'thinking' || activity === 'replying';
    const speed = busy ? 4 : 1.2;
    const pulse = STILL ? 1 : 1 + Math.sin(clock.elapsedTime * speed) * (busy ? 0.12 : 0.05);
    ref.current.scale.setScalar((online ? 26 : 18) * pulse);
    ref.current.material.opacity = killed ? 0.35 : online ? 1 : 0.45;
  });
  return (
    <sprite ref={ref}>
      <spriteMaterial map={texture} blending={AdditiveBlending} depthWrite={false} transparent />
    </sprite>
  );
}
