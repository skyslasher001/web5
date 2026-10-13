// Agents as luminous probes (SPEC §7): each has its colour, its own shape and a trail, and flies to
// whatever it's working on (`agent.step` targets). Idle probes orbit the Core; with the kill switch engaged
// they all park there (ARCHITECTURE.md §6.6).
import type { AgentInfo } from '@universe/shared-types';
import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  IcosahedronGeometry,
  Line,
  LineBasicMaterial,
  Mesh,
  MeshBasicMaterial,
  OctahedronGeometry,
  TetrahedronGeometry,
  TorusGeometry,
  Vector3,
  BoxGeometry,
  type BufferGeometry as Geometry,
} from 'three';
import { hueHex } from '../../lib/colors';
import { useProjects } from '../../lib/queries';
import { useUniverse, type ProbeTarget } from '../../state/store';
import { itemPosition } from './helpers';
import { STILL } from './interaction';
import { useLayout } from './layoutController';
import { useScene } from './sceneData';

const TRAIL = 28;
const SHAPES: (() => Geometry)[] = [
  () => new OctahedronGeometry(0.9),
  () => new TetrahedronGeometry(1.0),
  () => new IcosahedronGeometry(0.8),
  () => new BoxGeometry(1.1, 1.1, 1.1),
  () => new TorusGeometry(0.7, 0.22, 6, 12),
];

function targetPosition(
  target: ProbeTarget | undefined,
  projects: { id: string; name: string }[],
): Vector3 | null {
  if (!target) return null;
  const scene = useScene.getState().scene;
  if (target.kind === 'item') {
    const index = scene.index.get(target.id);
    return index === undefined ? null : itemPosition(index);
  }
  // Galaxies are named by id or by name (tools take either).
  const project = projects.find(
    (p) => p.id === target.id || p.name.toLowerCase() === target.id.toLowerCase(),
  );
  const g = project ? scene.galaxyIds.indexOf(project.id) : -1;
  const layout = useLayout.getState().current;
  if (g < 0 || !layout) return null;
  const c = layout.galaxyCentres;
  return new Vector3(c[g * 3], c[g * 3 + 1], c[g * 3 + 2]);
}

function Probe({ agent, slot, total }: { agent: AgentInfo; slot: number; total: number }) {
  const mesh = useRef<Mesh>(null);
  const projects = useProjects();
  const color = useMemo(() => new Color(hueHex(agent.color)), [agent.color]);
  const geometry = useMemo(() => SHAPES[slot % SHAPES.length]!(), [slot]);
  const trail = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new BufferAttribute(new Float32Array(TRAIL * 3), 3));
    const colors = new Float32Array(TRAIL * 3);
    for (let k = 0; k < TRAIL; k++) {
      const f = 1 - k / TRAIL;
      colors.set([color.r * f, color.g * f, color.b * f], k * 3);
    }
    g.setAttribute('color', new BufferAttribute(colors, 3));
    return new Line(
      g,
      new LineBasicMaterial({ vertexColors: true, transparent: true, blending: AdditiveBlending }),
    );
  }, [color]);
  const position = useRef(new Vector3(8, 0, 0));
  const history = useRef<Vector3[]>([]);

  useFrame(({ clock }, delta) => {
    const m = mesh.current;
    if (!m) return;
    const s = useUniverse.getState();
    const killed = s.killSwitch.engaged;
    const busy =
      !killed && (s.agentActivity[agent.id] === 'thinking' || s.agentActivity[agent.id] === 'replying');
    const goal = killed ? null : targetPosition(s.agentTargets[agent.id], projects.data ?? []);
    const t = clock.elapsedTime * (STILL ? 0 : 0.25) + (slot / Math.max(total, 1)) * Math.PI * 2;
    const parked = killed
      ? new Vector3(Math.cos(slot) * 3, 0, Math.sin(slot) * 3)
      : new Vector3(Math.cos(t) * (12 + slot), Math.sin(t * 1.3) * 3, Math.sin(t) * (12 + slot));
    const dest = goal
      ? goal.clone().add(new Vector3(Math.cos(t * 4) * 2.5, 1.5, Math.sin(t * 4) * 2.5))
      : parked;
    // Ease toward the destination: quick over long distances, gentle up close.
    position.current.lerp(dest, STILL ? 1 : 1 - Math.pow(0.04, delta));
    m.position.copy(position.current);
    m.rotation.x += delta * 0.8;
    m.rotation.y += delta * 1.1;
    m.scale.setScalar(busy ? 1.3 : 1);
    (m.material as MeshBasicMaterial).opacity = busy || goal ? 1 : 0.6;
    history.current.unshift(position.current.clone());
    history.current.length = Math.min(history.current.length, TRAIL);
    const attr = trail.geometry.getAttribute('position') as BufferAttribute;
    for (let k = 0; k < TRAIL; k++) {
      const p = history.current[Math.min(k, history.current.length - 1)]!;
      attr.setXYZ(k, p.x, p.y, p.z);
    }
    attr.needsUpdate = true;
  });

  return (
    <>
      <mesh ref={mesh} geometry={geometry}>
        <meshBasicMaterial color={color} transparent blending={AdditiveBlending} />
      </mesh>
      <primitive object={trail} />
    </>
  );
}

export function Probes() {
  const agents = useUniverse((s) => s.agents);
  return (
    <>
      {agents.map((a, i) => (
        <Probe key={a.id} agent={a} slot={i} total={agents.length} />
      ))}
    </>
  );
}
