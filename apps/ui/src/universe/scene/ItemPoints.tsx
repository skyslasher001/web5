// Every item in one THREE.Points (ADR-0012), with animated layout changes, search highlighting, the time
// slider, and a GPU picking pass for hover and click.
import { tokens } from '@universe/design-tokens';
import type { ItemType } from '@universe/shared-types';
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  NormalBlending,
  Points,
  Scene,
  ShaderMaterial,
  WebGLRenderTarget,
} from 'three';
import { ITEM_TYPES } from '../../lib/itemTypes';
import { useUniverse } from '../../state/store';
import { appearance } from './helpers';
import { easeInOutCubic, picker, STILL, tuning, useInteraction } from './interaction';
import { useLayout } from './layoutController';
import { useScene, type SceneData } from './sceneData';
import { PICK_FRAGMENT, PICK_VERTEX, pickColor, pickIndex, POINT_FRAGMENT, POINT_VERTEX } from './shaders';
import { styleFor, TYPE_ORDER } from './types';

const TRANSITION_MS = 900;
const EPOCH_2000 = 946_684_800;
const DAY = 86_400;
const NO_CUT = 1e9;

function buildAttributes(geometry: BufferGeometry, scene: SceneData) {
  const n = scene.n;
  const color = new Float32Array(n * 3);
  const size = new Float32Array(n);
  const shape = new Float32Array(n);
  const glow = new Float32Array(n);
  const seed = new Float32Array(n);
  const created = new Float32Array(n);
  const pick = new Float32Array(n * 3);
  const palette = new Map<string, Color>();
  const now = Date.now() / 1000;
  for (let i = 0; i < n; i++) {
    const type = TYPE_ORDER[scene.types[i]!]! as ItemType;
    const hue = ITEM_TYPES[type].hue;
    let c = palette.get(hue);
    if (!c) {
      c = new Color(tokens.color[hue]);
      palette.set(hue, c);
    }
    color.set([c.r, c.g, c.b], i * 3);
    const look = appearance(scene, i, now);
    size[i] = look.size;
    glow[i] = look.glow;
    shape[i] = styleFor(type, scene.ideaStages[i] ?? null).shape;
    seed[i] = (scene.hashes[i]! % 1000) / 1000;
    created[i] = (scene.created[i]! - EPOCH_2000) / DAY;
    pick.set(pickColor(i), i * 3);
  }
  geometry.setAttribute('aColor', new BufferAttribute(color, 3));
  geometry.setAttribute('aSize', new BufferAttribute(size, 1));
  geometry.setAttribute('aShape', new BufferAttribute(shape, 1));
  geometry.setAttribute('aGlow', new BufferAttribute(glow, 1));
  geometry.setAttribute('aSeed', new BufferAttribute(seed, 1));
  geometry.setAttribute('aCreated', new BufferAttribute(created, 1));
  geometry.setAttribute('aState', new BufferAttribute(new Float32Array(n), 1));
  geometry.setAttribute('aHidden', new BufferAttribute(new Float32Array(n), 1));
  geometry.setAttribute('aPick', new BufferAttribute(pick, 3));
}

interface Gpu {
  geometry: BufferGeometry;
  material: ShaderMaterial;
  pickScene: Scene;
  target: WebGLRenderTarget;
  dispose(): void;
}

function createGpu(): Gpu {
  const geometry = new BufferGeometry();
  const uniforms = {
    uMix: { value: 1 },
    uScale: { value: 1 },
    uSizeMul: { value: 1 },
    uTimeCut: { value: NO_CUT },
    uTime: { value: 0 },
    uDim: { value: 0 },
    uMinPx: { value: 1.1 },
  };
  const material = new ShaderMaterial({
    vertexShader: POINT_VERTEX,
    fragmentShader: POINT_FRAGMENT,
    uniforms,
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
  });
  // The picking pass shares the uniforms, so sizes, transitions and the time cut match what you see.
  const pickMaterial = new ShaderMaterial({
    vertexShader: PICK_VERTEX,
    fragmentShader: PICK_FRAGMENT,
    uniforms,
    blending: NormalBlending,
  });
  const pickScene = new Scene();
  pickScene.add(new Points(geometry, pickMaterial));
  const target = new WebGLRenderTarget(1, 1);
  return {
    geometry,
    material,
    pickScene,
    target,
    dispose() {
      geometry.dispose();
      material.dispose();
      pickMaterial.dispose();
      target.dispose();
    },
  };
}

export function ItemPoints({ sizeMul = 1 }: { sizeMul?: number }) {
  const { gl, camera, size } = useThree();
  const version = useScene((s) => s.version);
  const layout = useLayout((s) => s.current);
  const results = useInteraction((s) => s.results);
  const timeCut = useUniverse((s) => s.timeCut);
  const typeFilter = useUniverse((s) => s.typeFilter);
  const points = useRef<Points>(null);
  const gpu = useRef<Gpu | null>(null);
  const transition = useRef<{ start: number } | null>(null);
  const shown = useRef<{ ids: string[]; positions: Float32Array } | null>(null);
  const builtVersion = useRef(-1);

  // The GPU objects live for the component's lifetime; the <points> element gets them once mounted.
  useEffect(() => {
    const created = createGpu();
    gpu.current = created;
    if (points.current) {
      points.current.geometry = created.geometry;
      points.current.material = created.material;
    }
    return () => {
      created.dispose();
      gpu.current = null;
    };
  }, []);

  // A new layout (or new data): animate every item from where it is now to where it belongs.
  useEffect(() => {
    const g = gpu.current;
    const scene = useScene.getState().scene;
    if (!g || !layout || layout.sceneVersion !== version || layout.positions.length !== scene.n * 3) return;
    if (builtVersion.current !== version) {
      buildAttributes(g.geometry, scene);
      builtVersion.current = version;
    }
    const to = layout.positions;
    const from = new Float32Array(to.length);
    const prev = shown.current;
    const prevIndex = prev ? new Map(prev.ids.map((id, i) => [id, i])) : null;
    for (let i = 0; i < scene.n; i++) {
      const j = prevIndex?.get(scene.ids[i]!);
      const src = j !== undefined && prev ? prev.positions : to;
      const k = j !== undefined ? j : i;
      from[i * 3] = src[k * 3]!;
      from[i * 3 + 1] = src[k * 3 + 1]!;
      from[i * 3 + 2] = src[k * 3 + 2]!;
    }
    g.geometry.setAttribute('position', new BufferAttribute(to, 3));
    g.geometry.setAttribute('aFrom', new BufferAttribute(from, 3));
    g.geometry.computeBoundingSphere();
    shown.current = { ids: scene.ids, positions: to };
    const animate = prev !== null && !STILL;
    g.material.uniforms.uMix!.value = animate ? 0 : 1;
    transition.current = animate ? { start: performance.now() } : null;
  }, [layout, version]);

  // Search results glow; everything else dims.
  useEffect(() => {
    const g = gpu.current;
    const attr = g?.geometry.getAttribute('aState') as BufferAttribute | undefined;
    if (!g || !attr) return;
    const state = attr.array as Float32Array;
    state.fill(0);
    for (const i of results) if (i < state.length) state[i] = 1;
    attr.needsUpdate = true;
    g.material.uniforms.uDim!.value = results.length ? 1 : 0;
  }, [results, layout]);

  // The type chips hide every other type.
  useEffect(() => {
    const g = gpu.current;
    const attr = g?.geometry.getAttribute('aHidden') as BufferAttribute | undefined;
    if (!attr) return;
    const hidden = attr.array as Float32Array;
    const scene = useScene.getState().scene;
    const shown = new Set(typeFilter.map((t) => TYPE_ORDER.indexOf(t)));
    for (let i = 0; i < hidden.length; i++) hidden[i] = shown.size && !shown.has(scene.types[i]!) ? 1 : 0;
    attr.needsUpdate = true;
  }, [typeFilter, layout]);

  useEffect(() => {
    const g = gpu.current;
    if (g) g.material.uniforms.uTimeCut!.value = timeCut === null ? NO_CUT : (timeCut - EPOCH_2000) / DAY;
  }, [timeCut]);

  // GPU picking: render the id-coloured points into the one pixel under the pointer.
  useEffect(() => {
    const pixel = new Uint8Array(4);
    picker.pick = (x, y) => {
      const g = gpu.current;
      if (!g || !g.geometry.getAttribute('position')) return -1;
      const ratio = gl.getPixelRatio();
      const cam = camera as typeof camera & {
        setViewOffset?: (fw: number, fh: number, x: number, y: number, w: number, h: number) => void;
        clearViewOffset?: () => void;
      };
      cam.setViewOffset?.(
        size.width * ratio,
        size.height * ratio,
        Math.round(x * ratio),
        Math.round(y * ratio),
        1,
        1,
      );
      const previous = gl.getRenderTarget();
      gl.setRenderTarget(g.target);
      gl.setClearColor(0x000000, 0);
      gl.clear();
      gl.render(g.pickScene, camera);
      gl.readRenderTargetPixels(g.target, 0, 0, 1, 1, pixel);
      gl.setRenderTarget(previous);
      cam.clearViewOffset?.();
      return pixel[3] ? pickIndex(pixel[0]!, pixel[1]!, pixel[2]!) : -1;
    };
    return () => {
      picker.pick = () => -1;
    };
  }, [gl, camera, size]);

  useFrame(({ clock }) => {
    const g = gpu.current;
    if (!g) return;
    const u = g.material.uniforms;
    u.uTime!.value = clock.elapsedTime;
    u.uSizeMul!.value = sizeMul * tuning.pointScale;
    u.uMinPx!.value = tuning.minPx;
    const fov = 'fov' in camera ? (camera.fov as number) : 50;
    u.uScale!.value = (size.height * gl.getPixelRatio()) / (2 * Math.tan((fov * Math.PI) / 360));
    const t = transition.current;
    if (t) {
      const p = Math.min(1, (performance.now() - t.start) / TRANSITION_MS);
      u.uMix!.value = easeInOutCubic(p);
      if (p >= 1) transition.current = null;
    }
  });

  return <points ref={points} frustumCulled={false} />;
}
