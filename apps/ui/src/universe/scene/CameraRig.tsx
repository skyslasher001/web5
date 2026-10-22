// Orbit controls plus eased camera flights (SPEC §7: 600–1200 ms, distance-scaled; instant with reduced
// motion). Selecting a galaxy, an item or search results flies there; H flies home to the Core.
// Zoom is our own (zoom.ts): log-scale, eased, toward the point under the pointer, with clip planes that
// follow the distance, so it stays smooth from the whole universe down to a single item.
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import { Plane, Raycaster, Vector2, Vector3, type PerspectiveCamera } from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { useUniverse } from '../../state/store';
import { flightDuration, flyOnce, itemPosition, resetRig, rig } from './helpers';
import { easeInOutCubic, STILL, useInteraction } from './interaction';
import { useLayout } from './layoutController';
import { useScene } from './sceneData';
import {
  clipPlanes,
  easeToward,
  focusGalaxy,
  wheelFactor,
  zoomAnchor,
  zoomFraction,
  zoomGoal,
  zoomLimits,
} from './zoom';

interface Flight {
  fromPos: Vector3;
  fromTarget: Vector3;
  toPos: Vector3;
  toTarget: Vector3;
  start: number;
  duration: number;
}

interface Zoom {
  goal: number;
  anchor: Vector3;
}

function limits() {
  return zoomLimits(useLayout.getState().current?.extent ?? 300);
}

function homePose() {
  const extent = useLayout.getState().current?.extent ?? 300;
  return { pos: new Vector3(0, extent * 0.5, extent * 1.3), target: new Vector3(0, 0, 0) };
}

export function CameraRig() {
  const { camera, gl } = useThree();
  const controls = useRef<OrbitControls | null>(null);
  const flight = useRef<Flight | null>(null);
  const zoom = useRef<Zoom | null>(null);
  const lastFlight = useRef<{ planned: number; actual: number } | null>(null);
  const placedOnce = useRef(false);
  const layout = useLayout((s) => s.current);
  const selectedItem = useUniverse((s) => s.selectedItemId);
  const selectedProject = useUniverse((s) => s.selectedProjectId);
  const homeTick = useUniverse((s) => s.homeTick);
  const view = useUniverse((s) => s.view);
  const results = useInteraction((s) => s.results);

  useEffect(() => {
    const c = new OrbitControls(camera, gl.domElement);
    c.enableDamping = !STILL;
    c.dampingFactor = 0.08;
    c.enableZoom = false; // zoom is ours, below
    c.minDistance = 0.5;
    c.maxDistance = 80000;
    c.screenSpacePanning = true;
    controls.current = c;

    // Start (or retarget) a zoom: move the goal distance and keep `anchor` fixed on screen.
    const zoomBy = (request: { by: number } | { to: number }, anchor: Vector3) => {
      flight.current = null; // zooming takes over from a flight
      const { min, max } = limits();
      const distance = camera.position.distanceTo(c.target);
      zoom.current = { goal: zoomGoal(request, zoom.current?.goal ?? null, distance, min, max), anchor };
    };
    // The point under the pointer: the item it's on, else where the pointer ray meets the plane through the
    // orbit target, facing the camera.
    const raycaster = new Raycaster();
    const plane = new Plane();
    const ndc = new Vector2();
    const forward = new Vector3();
    const pointUnder = (e: WheelEvent): Vector3 => {
      const hovered = useInteraction.getState().hovered;
      const item = hovered >= 0 ? itemPosition(hovered) : null;
      if (item) return item;
      const rect = gl.domElement.getBoundingClientRect();
      ndc.set(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(ndc, camera);
      plane.setFromNormalAndCoplanarPoint(camera.getWorldDirection(forward), c.target);
      return raycaster.ray.intersectPlane(plane, new Vector3()) ?? c.target.clone();
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoomBy({ by: wheelFactor(e.deltaY, e.deltaMode, e.ctrlKey) }, pointUnder(e));
    };
    gl.domElement.addEventListener('wheel', onWheel, { passive: false });
    rig.zoomBy = (factor) => zoomBy({ by: factor }, c.target.clone());
    // The slider sets the goal outright: dragging it mid-glide must not compound on the goal in flight.
    rig.zoomTo = (fraction) => zoomBy({ to: fraction }, c.target.clone());
    rig.zoom = () => {
      const { min, max } = limits();
      const distance = zoom.current?.goal ?? camera.position.distanceTo(c.target);
      const layout = useLayout.getState().current;
      return {
        fraction: zoomFraction(distance, min, max),
        galaxy:
          layout?.kind === 'project'
            ? focusGalaxy(
                c.target,
                camera.position.distanceTo(c.target),
                layout.galaxyCentres,
                layout.galaxyRadii,
              )
            : -1,
      };
    };

    const flyToPose = (toPos: Vector3, toTarget: Vector3) => {
      zoom.current = null; // a flight takes over from a zoom
      if (STILL) {
        camera.position.copy(toPos);
        c.target.copy(toTarget);
        c.update();
        flight.current = null;
        return;
      }
      flight.current = {
        fromPos: camera.position.clone(),
        fromTarget: c.target.clone(),
        toPos,
        toTarget,
        start: performance.now(),
        duration: flightDuration(camera.position.distanceTo(toPos)),
      };
    };
    rig.flyTo = (target, distance) => {
      // Keep the current viewing direction, so a flight feels like moving, not teleporting.
      const dir = camera.position.clone().sub(c.target);
      if (dir.lengthSq() < 1e-6) dir.set(0, 0.4, 1);
      dir.normalize();
      flyToPose(target.clone().addScaledVector(dir, distance), target.clone());
    };
    rig.home = () => {
      const { pos, target } = homePose();
      flyToPose(pos, target);
    };
    rig.state = () => ({
      position: camera.position.toArray(),
      target: c.target.toArray(),
      flying: flight.current !== null,
      lastFlight: lastFlight.current,
    });
    return () => {
      gl.domElement.removeEventListener('wheel', onWheel);
      c.dispose();
      controls.current = null;
      resetRig();
    };
  }, [camera, gl]);

  // First layout: start at home, framing everything.
  useEffect(() => {
    const c = controls.current;
    if (!layout || !c || placedOnce.current) return;
    placedOnce.current = true;
    const { pos, target } = homePose();
    camera.position.copy(pos);
    c.target.copy(target);
    c.update();
  }, [layout, camera]);

  useEffect(() => {
    if (homeTick) rig.home();
  }, [homeTick]);

  // A different layout moves everything: re-frame what you were looking at (its galaxy, or the whole universe).
  const kind = layout?.kind;
  useEffect(() => {
    if (!kind || !placedOnce.current) return;
    const s = useUniverse.getState();
    if (s.selectedItemId || s.selectedProjectId) return; // the selection effects below fly there
    rig.home();
  }, [kind]);

  // The selection effects re-run when a layout for a newer scene arrives (a just-selected item may only be
  // placed then), but fly once per selection and layout kind: a data refresh (or a Semantic poll) publishes
  // a new layout object and must not yank the camera back.
  const sceneVersion = layout?.sceneVersion;
  const flownGalaxy = useRef('');
  const flownItem = useRef('');

  // Fly to a selected galaxy (Galaxy zoom).
  useEffect(() => {
    const key = selectedProject && view === 'universe' && !selectedItem ? `${selectedProject}:${kind}` : null;
    flyOnce(flownGalaxy, key, () => {
      const current = useLayout.getState().current;
      const { scene, version } = useScene.getState();
      const g = scene.galaxyIds.indexOf(selectedProject ?? '');
      if (!current || current.sceneVersion !== version || g < 0 || g >= current.galaxyRadii.length) return false;
      const c = current.galaxyCentres;
      rig.flyTo(new Vector3(c[g * 3], c[g * 3 + 1], c[g * 3 + 2]), Math.max(30, current.galaxyRadii[g]! * 2.8));
      return true;
    });
  }, [selectedProject, view, selectedItem, kind, sceneVersion]);

  // Fly to a selected item (System zoom: the item and its neighbours), again when the layout changes.
  useEffect(() => {
    const key = selectedItem && view === 'universe' ? `${selectedItem}:${kind}` : null;
    flyOnce(flownItem, key, () => {
      const index = useScene.getState().scene.index.get(selectedItem ?? '');
      const position = index === undefined ? null : itemPosition(index);
      if (position) rig.flyTo(position, 16);
      return position !== null;
    });
  }, [selectedItem, view, kind, sceneVersion]);

  // Search results: frame the constellation when the results change. A refresh that returns the same
  // results doesn't move the camera (it would undo flying to the one you picked with Enter).
  const framed = useRef('');
  useEffect(() => {
    const key = results.join(',');
    if (key === framed.current) return;
    framed.current = key;
    if (!results.length || view !== 'universe') return;
    const points = results
      .slice(0, 40)
      .map(itemPosition)
      .filter((p): p is Vector3 => p !== null);
    if (!points.length) return;
    const centre = points.reduce((s, p) => s.add(p), new Vector3()).divideScalar(points.length);
    const radius = Math.max(...points.map((p) => p.distanceTo(centre)));
    rig.flyTo(centre, Math.max(18, radius * 2.4));
  }, [results, view]);

  useFrame((state, delta) => {
    const c = controls.current;
    if (!c) return;
    const z = zoom.current;
    if (z) {
      const distance = camera.position.distanceTo(c.target);
      const next = easeToward(distance, z.goal, delta, STILL ? Infinity : undefined);
      const t = zoomAnchor(c.target, z.anchor, next / distance);
      const dir = camera.position.clone().sub(c.target).normalize();
      c.target.set(t.x, t.y, t.z);
      camera.position.copy(c.target).addScaledVector(dir, next);
      if (next === z.goal) zoom.current = null;
    }
    // Clip planes follow the distance (depth precision up close, the whole universe from afar).
    const cam = state.camera as PerspectiveCamera;
    const planes = clipPlanes(camera.position.distanceTo(c.target));
    if (Math.abs(cam.near / planes.near - 1) > 0.15 || Math.abs(cam.far / planes.far - 1) > 0.15) {
      cam.near = planes.near;
      cam.far = planes.far;
      cam.updateProjectionMatrix();
    }
    const f = flight.current;
    if (f) {
      const t = Math.min(1, (performance.now() - f.start) / f.duration);
      const e = easeInOutCubic(t);
      camera.position.lerpVectors(f.fromPos, f.toPos, e);
      c.target.lerpVectors(f.fromTarget, f.toTarget, e);
      if (t >= 1) {
        lastFlight.current = { planned: f.duration, actual: Math.round(performance.now() - f.start) };
        flight.current = null;
      }
    }
    c.update();
  });
  return null;
}
