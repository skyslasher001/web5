// Lite mode (SPEC §7): the same universe as a 2D WebGL graph (sigma), for machines without a capable GPU.
// Same positions (seen from above), same colours, same HUD; search, selection and "home" move the camera.
import { tokens } from '@universe/design-tokens';
import type { ItemType } from '@universe/shared-types';
import Graph from 'graphology';
import { useEffect, useRef } from 'react';
import Sigma from 'sigma';
import { hueHex } from '../lib/colors';
import { ITEM_TYPES } from '../lib/itemTypes';
import { useProjects } from '../lib/queries';
import { useUniverse } from '../state/store';
import { appearance, rig } from './scene/helpers';
import { useInteraction } from './scene/interaction';
import { useLayout } from './scene/layoutController';
import { useScene } from './scene/sceneData';
import { styleFor, TYPE_ORDER } from './scene/types';

interface NodeAttrs {
  x: number;
  y: number;
  size: number;
  color: string;
  label: string;
  galaxy?: boolean;
  forceLabel?: boolean;
  zIndex?: number;
}

const DIMMED = tokens.color.space['3'];

/** A node's position in the camera's coordinate system (sigma's "framed graph", 0–1). */
function framed(renderer: Sigma<NodeAttrs>, node: string): { x: number; y: number } | null {
  const g = renderer.getGraph();
  if (!g.hasNode(node)) return null;
  const { x, y } = g.getNodeAttributes(node);
  return renderer.viewportToFramedGraph(renderer.graphToViewport({ x, y }));
}

export default function LiteScene() {
  const container = useRef<HTMLDivElement>(null);
  const sigma = useRef<Sigma<NodeAttrs> | null>(null);
  const graph = useRef(new Graph<NodeAttrs>({ type: 'directed', multi: false }));
  const layout = useLayout((s) => s.current);
  const version = useScene((s) => s.version);
  const results = useInteraction((s) => s.results);
  const selected = useUniverse((s) => s.selectedItemId);
  const homeTick = useUniverse((s) => s.homeTick);
  const projects = useProjects();

  // One renderer for the component's lifetime.
  useEffect(() => {
    if (!container.current) return;
    const g = graph.current;
    const renderer = new Sigma<NodeAttrs>(g, container.current, {
      renderLabels: true,
      labelRenderedSizeThreshold: 7,
      labelColor: { color: tokens.color.ink['2'] },
      labelFont: 'Inter Variable, system-ui, sans-serif',
      labelSize: 11,
      defaultEdgeColor: '#1f3a4f',
      zIndex: false, // sorting 50k nodes by z-index cost ~2 s a frame in software rendering (measured)
      minCameraRatio: 0.002,
      maxCameraRatio: 4,
      hideEdgesOnMove: true,
      hideLabelsOnMove: true, // labels for 50k nodes are the slowest part of a frame
    });
    renderer.on('clickNode', ({ node }) => {
      const s = useUniverse.getState();
      if (g.getNodeAttribute(node, 'galaxy')) s.selectProject(node.slice(2));
      else s.selectItem(node);
    });
    renderer.on('doubleClickNode', ({ node, event }) => {
      event.preventSigmaDefault();
      const s = useUniverse.getState();
      if (g.getNodeAttribute(node, 'galaxy')) s.openDashboard(node.slice(2));
      else s.openViewer(node);
    });
    renderer.on('clickStage', () => useUniverse.getState().zoomOut());
    sigma.current = renderer;
    const camera = renderer.getCamera();
    rig.state = () => {
      const c = camera.getState();
      return {
        position: [c.x, c.y, c.ratio],
        target: [c.x, c.y, 0],
        flying: camera.isAnimated(),
        lastFlight: null,
      };
    };
    return () => {
      renderer.kill();
      sigma.current = null;
    };
  }, []);

  // Rebuild the graph when the data or the layout changes (positions seen from above: x, -z).
  useEffect(() => {
    const scene = useScene.getState().scene;
    const renderer = sigma.current;
    if (!renderer || !layout || layout.positions.length !== scene.n * 3) return;
    const g = graph.current;
    g.clear();
    const p = layout.positions;
    const now = Date.now() / 1000;
    for (let i = 0; i < scene.n; i++) {
      const type = TYPE_ORDER[scene.types[i]!]! as ItemType;
      const look = appearance(scene, i, now);
      g.addNode(scene.ids[i]!, {
        x: p[i * 3]!,
        y: -p[i * 3 + 2]!,
        size: 1.2 + look.size * 1.4,
        color: tokens.color[ITEM_TYPES[type].hue],
        label: `${scene.titles[i]} · ${styleFor(type, scene.ideaStages[i] ?? null).body}`,
      });
    }
    const names = new Map((projects.data ?? []).map((pr) => [pr.id, pr]));
    scene.galaxyIds.forEach((id, k) => {
      const project = names.get(id);
      if (!project || k * 3 + 2 >= layout.galaxyCentres.length) return;
      g.addNode(`g:${id}`, {
        x: layout.galaxyCentres[k * 3]!,
        y: -layout.galaxyCentres[k * 3 + 2]!,
        size: 6 + Math.min(14, (layout.galaxyRadii[k] ?? 8) / 4),
        color: hueHex(project.color_token),
        label: project.name,
        galaxy: true,
        forceLabel: layout.kind === 'project',
        zIndex: 2,
      });
    });
    if (layout.kind === 'graph') {
      for (let k = 0; k < scene.linksA.length; k++) {
        const a = scene.ids[scene.linksA[k]!]!;
        const b = scene.ids[scene.linksB[k]!]!;
        if (!g.hasEdge(a, b))
          g.addEdge(a, b, { size: 0.5, color: scene.linkSuggested[k] ? '#3b2f66' : '#1f3a4f' });
      }
    }
    renderer.refresh();
  }, [layout, version, projects.data]);

  // Search results stand out; the rest dims. The camera frames the results.
  useEffect(() => {
    const renderer = sigma.current;
    if (!renderer) return;
    const scene = useScene.getState().scene;
    const hits = new Set(results.map((i) => scene.ids[i]));
    renderer.setSetting(
      'nodeReducer',
      hits.size || selected
        ? (node, data) => {
            if (node === selected) return { ...data, size: data.size * 2.2, forceLabel: true, zIndex: 3 };
            if (!hits.size) return data;
            if (hits.has(node)) return { ...data, size: data.size * 1.8, zIndex: 2 };
            return { ...data, color: DIMMED, label: '', zIndex: 0 };
          }
        : null,
    );
    if (hits.size && !selected) {
      const points = [...hits]
        .slice(0, 40)
        .map((id) => (id ? framed(renderer, id) : null))
        .filter((d): d is { x: number; y: number } => d !== null);
      if (points.length) {
        const xs = points.map((d) => d.x);
        const ys = points.map((d) => d.y);
        const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
        void renderer.getCamera().animate(
          {
            x: (Math.max(...xs) + Math.min(...xs)) / 2,
            y: (Math.max(...ys) + Math.min(...ys)) / 2,
            ratio: Math.max(0.02, span * 1.6),
          },
          { duration: 800 },
        );
      }
    }
  }, [results, selected, layout]);

  // Fly to a selected item.
  useEffect(() => {
    const renderer = sigma.current;
    if (!renderer || !selected || !graph.current.hasNode(selected)) return;
    const d = framed(renderer, selected);
    if (d) void renderer.getCamera().animate({ x: d.x, y: d.y, ratio: 0.05 }, { duration: 800 });
  }, [selected]);

  useEffect(() => {
    if (homeTick) void sigma.current?.getCamera().animatedReset({ duration: 800 });
  }, [homeTick]);

  return (
    <div
      ref={container}
      className="absolute inset-0"
      aria-label="Universe view (Lite: 2D graph)"
      data-testid="lite-view"
    />
  );
}
