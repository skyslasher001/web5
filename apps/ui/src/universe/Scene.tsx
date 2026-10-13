// The universe (Phase 4, ADR-0012): every item drawn by type in one of four layouts, galaxies, filaments,
// comets, agent probes and search constellations, with GPU picking and camera flights. Lite mode (a 2D
// WebGL graph) takes over when WebGL is missing or the Lite quality preset is chosen.
import { Canvas, useThree } from '@react-three/fiber';
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { useApi } from '../lib/api-context';
import { useProjects } from '../lib/queries';
import { onCoreEvent, useUniverse } from '../state/store';
import { PRESETS } from './quality';
import { CoreStar, Starfield } from './scene/Backdrop';
import { Bloom } from './scene/Bloom';
import { CameraRig } from './scene/CameraRig';
import { rig } from './scene/helpers';
import { tuning } from './scene/interaction';
import { Comets } from './scene/Comets';
import { Filaments } from './scene/Filaments';
import { Galaxies, GalaxyLabels } from './scene/Galaxies';
import { ItemLabels } from './scene/ItemLabels';
import { ItemPoints } from './scene/ItemPoints';
import { LayoutController, useLayout } from './scene/layoutController';
import { OverlayContext } from './scene/overlay';
import { PhotoPlanets } from './scene/PhotoPlanets';
import { Probes } from './scene/Probes';
import { SceneLoader, useScene } from './scene/sceneData';
import { SelectionRing } from './scene/Selection';
import { useConstellation } from './scene/useConstellation';
import { webglAvailable } from './webgl';

/** Static fallback when WebGL is unavailable and Lite can't run either: CSS stars over the nebula. */
function StaticStars() {
  return <div className="static-stars absolute inset-0" aria-hidden data-testid="static-stars" />;
}

// sigma is only loaded when Lite is in use.
const LiteScene = lazy(() => import('./LiteScene'));

export default function Scene() {
  const [webgl] = useState(webglAvailable);
  const quality = useUniverse((s) => s.quality);
  const initQuality = useUniverse((s) => s.initQuality);
  useEffect(() => initQuality(webgl), [initQuality, webgl]);
  if (!webgl) return <StaticStars />;
  if (quality === null) return null;
  return quality === 'lite' ? <LiteUniverse /> : <WebGLScene />;
}

function LiteUniverse() {
  useUniverseData();
  useConstellation();
  return (
    <Suspense fallback={null}>
      <LiteScene />
    </Suspense>
  );
}

/** Loads the scene data and keeps the chosen layout computed (shared by the 3D view and Lite). */
function useUniverseData() {
  const api = useApi();
  const projects = useProjects();
  const online = useUniverse((s) => s.connection === 'online');
  const layoutKind = useUniverse((s) => s.layout);
  const version = useScene((s) => s.version);
  const loader = useMemo(() => new SceneLoader(api), [api]);
  const controller = useMemo(() => new LayoutController(api), [api]);

  useEffect(() => () => controller.dispose(), [controller]);
  useEffect(() => {
    if (online) void loader.load();
  }, [online, loader]);
  useEffect(
    () =>
      onCoreEvent((event) => {
        loader.onEvent(event);
        if (event.type === 'layout.updated') controller.semanticUpdated();
      }),
    [loader, controller],
  );
  useEffect(() => {
    if (projects.data) loader.setGalaxyOrder(projects.data.map((p) => p.id));
  }, [projects.data, loader]);
  useEffect(() => {
    void controller.show(layoutKind, useScene.getState().scene, version);
  }, [layoutKind, version, controller]);
  // Read-only hooks for the end-to-end tests (camera pose, item count, current layout).
  useEffect(() => {
    const w = window as unknown as Record<string, Record<string, unknown>>;
    w.__universeDebug = {
      ...(w.__universeDebug ?? {}),
      camera: () => rig.state(),
      items: () => useScene.getState().scene.n,
      layout: () => useLayout.getState().current?.kind ?? null,
    };
  }, []);
}

/** Read-only view of the renderer for the end-to-end tests: draw calls, and named objects to time. */
function DebugBridge() {
  const { gl, scene } = useThree();
  useEffect(() => {
    const w = window as unknown as Record<string, Record<string, unknown>>;
    w.__universeDebug = {
      ...(w.__universeDebug ?? {}),
      renderInfo: () => ({ calls: gl.info.render.calls, points: gl.info.render.points }),
      setPointScale: (scale: number) => {
        tuning.pointScale = scale;
      },
      setVisible: (name: string, visible: boolean) => {
        scene.traverse((o) => {
          if (o.name === name) o.visible = visible;
        });
      },
    };
  }, [gl, scene]);
  return null;
}

function WebGLScene() {
  useUniverseData();
  useConstellation();
  const overlay = useRef<HTMLDivElement>(null);
  // Behind the grid and list the universe is a still backdrop: render on demand instead of 60 times a second.
  const live = useUniverse((s) => s.view === 'universe');
  const smooth = useUniverse((s) => s.smooth);
  const quality = useUniverse((s) => s.quality);
  const preset = PRESETS[quality === 'ultra' || quality === 'high' ? quality : 'balanced'];
  useEffect(() => {
    tuning.pointScale = preset.pointScale;
    tuning.minPx = preset.minPx;
  }, [preset]);

  return (
    <OverlayContext.Provider value={overlay}>
      <Canvas
        className="absolute inset-0"
        frameloop={live ? 'always' : 'demand'}
        camera={{ position: [0, 120, 320], fov: 50, near: 0.5, far: 20000 }}
        dpr={smooth ? 1 : preset.dpr}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        aria-label="Universe view"
        data-testid="universe-canvas"
      >
        <Starfield />
        <CoreStar />
        <group name="galaxies">
          <Galaxies />
        </group>
        <group name="items">
          <ItemPoints />
        </group>
        <group name="filaments">
          <Filaments />
        </group>
        <group name="comets">
          <Comets />
        </group>
        <PhotoPlanets max={preset.photoPlanets} />
        <SelectionRing />
        <group name="probes">
          <Probes />
        </group>
        <ItemLabels count={preset.labels} />
        <CameraRig />
        <DebugBridge />
        {preset.bloom && !smooth && <Bloom />}
      </Canvas>
      <div ref={overlay} className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
        <GalaxyLabels />
      </div>
    </OverlayContext.Provider>
  );
}
