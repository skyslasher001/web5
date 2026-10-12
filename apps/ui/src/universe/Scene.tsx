// Phase 1 universe: a parallax starfield, the Core (home star) and one galaxy per project.
// The full celestial mapping, layouts, LOD and camera flights arrive in Phase 4.
import { tokens } from '@universe/design-tokens';
import type { Project } from '@universe/shared-types';
import { Canvas, useFrame } from '@react-three/fiber';
import { createContext, useContext, useMemo, useRef, useState, type RefObject } from 'react';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  Vector3,
  type Group,
  type Points,
  type Sprite,
} from 'three';
import { hueHex } from '../lib/colors';
import { useProjects } from '../lib/queries';
import { useUniverse } from '../state/store';
import { galaxyTexture, glowTexture } from './textures';
import { webglAvailable } from './webgl';

// Read once: motion preferences rarely change mid-session, and the scene stays pure during render.
const STILL = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Deterministic PRNG so the starfield is identical on every render (and launch). */
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function Starfield({ count = 4000 }: { count?: number }) {
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
      const r = 120 + random() * 380;
      const theta = random() * Math.PI * 2;
      const phi = Math.acos(2 * random() - 1);
      positions.set(
        [r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta)],
        i * 3,
      );
      const c = palette[random() < 0.82 ? Math.floor(random() * 2) : 2 + Math.floor(random() * 2)]!;
      colors.set([c.r, c.g, c.b], i * 3);
    }
    const g = new BufferGeometry();
    g.setAttribute('position', new BufferAttribute(positions, 3));
    g.setAttribute('color', new BufferAttribute(colors, 3));
    return g;
  }, [count]);
  useFrame((_, delta) => {
    if (ref.current && !STILL) ref.current.rotation.y += delta * 0.006;
  });
  return (
    <points ref={ref} geometry={geometry}>
      <pointsMaterial size={1.1} sizeAttenuation vertexColors transparent opacity={0.85} depthWrite={false} />
    </points>
  );
}

function CoreStar() {
  const ref = useRef<Sprite>(null);
  const activity = useUniverse((s) => s.agentActivity.core ?? 'idle');
  const online = useUniverse((s) => s.connection === 'online');
  const texture = useMemo(() => glowTexture(tokens.color.accent), []);
  useFrame(({ clock }) => {
    if (!ref.current) return;
    const busy = activity === 'thinking' || activity === 'replying';
    const speed = busy ? 4 : 1.2;
    const pulse = STILL ? 1 : 1 + Math.sin(clock.elapsedTime * speed) * (busy ? 0.12 : 0.05);
    const base = online ? 9 : 6;
    ref.current.scale.setScalar(base * pulse);
    ref.current.material.opacity = online ? 1 : 0.45;
  });
  return (
    <sprite ref={ref}>
      <spriteMaterial map={texture} blending={AdditiveBlending} depthWrite={false} transparent />
    </sprite>
  );
}

/** Galaxy labels live in a plain DOM overlay; each galaxy moves its own label from the render loop. */
const LabelLayer = createContext<RefObject<HTMLDivElement | null> | null>(null);
const scratch = new Vector3();

function Galaxy({ project, index, total }: { project: Project; index: number; total: number }) {
  const group = useRef<Group>(null);
  const anchor = useRef<Group>(null);
  const layer = useContext(LabelLayer);
  const selected = useUniverse((s) => s.selectedProjectId === project.id);
  const select = useUniverse((s) => s.selectProject);
  const [hover, setHover] = useState(false);
  const color = hueHex(project.color_token);
  const texture = useMemo(() => galaxyTexture(color, project.layout_seed + 1), [color, project.layout_seed]);
  // An ellipse around the Core that stays inside the HUD's free centre area at the default camera.
  const angle = (index / Math.max(total, 1)) * Math.PI * 2 + Math.PI / 4;
  const position: [number, number, number] = [
    Math.cos(angle) * 16,
    Math.sin(angle) * 9,
    -Math.sin(angle) * 4,
  ];
  useFrame(({ camera, size }, delta) => {
    if (group.current && !STILL) group.current.rotation.z += delta * 0.03;
    const label = layer?.current?.querySelector<HTMLElement>(`[data-label="${project.id}"]`);
    if (label && anchor.current) {
      anchor.current.getWorldPosition(scratch).project(camera);
      const x = ((scratch.x + 1) / 2) * size.width;
      const y = ((1 - scratch.y) / 2) * size.height;
      label.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px)`;
      label.style.opacity = scratch.z < 1 ? '1' : '0';
    }
  });
  const scale = selected ? 11 : hover ? 10 : 9;
  return (
    <group position={position}>
      <group ref={group}>
        <sprite
          scale={[scale, scale, 1]}
          onClick={(e) => {
            e.stopPropagation();
            select(project.id);
          }}
          onPointerOver={(e) => {
            e.stopPropagation();
            setHover(true);
            document.body.style.cursor = 'pointer';
          }}
          onPointerOut={() => {
            setHover(false);
            document.body.style.cursor = '';
          }}
        >
          <spriteMaterial
            map={texture}
            blending={AdditiveBlending}
            depthWrite={false}
            transparent
            opacity={selected || hover ? 1 : 0.85}
          />
        </sprite>
      </group>
      <group ref={anchor} position={[0, -5.6, 0]} />
    </group>
  );
}

function CameraDrift() {
  useFrame(({ camera, pointer }) => {
    if (STILL) return;
    camera.position.x += (pointer.x * 4 - camera.position.x) * 0.02;
    camera.position.y += (8 + pointer.y * 2.5 - camera.position.y) * 0.02;
    camera.lookAt(0, 0, 0);
  });
  return null;
}

/** Static fallback when WebGL is unavailable: CSS stars over the nebula backdrop (Lite mode lands in Phase 4). */
function StaticStars() {
  return <div className="static-stars absolute inset-0" aria-hidden data-testid="static-stars" />;
}

export default function Scene() {
  const [webgl] = useState(webglAvailable);
  return webgl ? <WebGLScene /> : <StaticStars />;
}

function WebGLScene() {
  const projects = useProjects();
  const select = useUniverse((s) => s.selectProject);
  const list = projects.data ?? [];
  const labels = useRef<HTMLDivElement>(null);
  const selected = useUniverse((s) => s.selectedProjectId);
  return (
    <LabelLayer.Provider value={labels}>
      <Canvas
        className="absolute inset-0"
        camera={{ position: [0, 8, 62], fov: 50, near: 0.1, far: 2000 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        onPointerMissed={() => select(null)}
        aria-label="Universe view"
      >
        <Starfield />
        <group position={[-3.5, 1, 0]}>
          <CoreStar />
          {list.map((p, i) => (
            <Galaxy key={p.id} project={p} index={i} total={list.length} />
          ))}
        </group>
        <CameraDrift />
      </Canvas>
      <div ref={labels} className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
        {list.map((p) => (
          <span
            key={p.id}
            data-label={p.id}
            className="absolute top-0 left-0 font-display text-xs whitespace-nowrap transition-colors duration-200"
            style={{
              color: selected === p.id ? tokens.color.ink['1'] : tokens.color.ink['3'],
              letterSpacing: '0.06em',
              opacity: 0,
            }}
          >
            {p.name}
          </span>
        ))}
      </div>
    </LabelLayer.Provider>
  );
}
