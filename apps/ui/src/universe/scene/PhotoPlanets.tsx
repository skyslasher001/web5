// Photos are planets whose surface is the photo itself as you approach (SPEC §7). Only the nearest few get
// a real sphere with their thumbnail; everything else stays a point (level of detail).
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef, useState } from 'react';
import { SRGBColorSpace, Texture, TextureLoader, Vector3 } from 'three';
import { useApi } from '../../lib/api-context';
import { nearestInFront, texturesToEvict } from './helpers';
import { useLayout } from './layoutController';
import { useScene } from './sceneData';
import { TYPE_CODE } from './types';

const REACH = 45;
const REFRESH_MS = 400;
const PHOTO_CODES = new Set(['photo', 'screenshot'].map((t) => TYPE_CODE.get(t)!));

interface Planet {
  index: number;
  id: string;
  texture: Texture;
}

export function PhotoPlanets({ max = 16 }: { max?: number }) {
  const api = useApi();
  const { camera } = useThree();
  const [planets, setPlanets] = useState<Planet[]>([]);
  const cache = useRef(new Map<string, Texture | 'missing' | 'loading'>());
  const last = useRef(0);
  const forward = useRef(new Vector3());
  const alive = useRef(true);

  useEffect(() => {
    const textures = cache.current;
    alive.current = true;
    return () => {
      alive.current = false; // a thumbnail that arrives later is disposed, not cached
      for (const t of textures.values()) if (t instanceof Texture) t.dispose();
      textures.clear();
    };
  }, []);

  useFrame(() => {
    const now = performance.now();
    if (now - last.current < REFRESH_MS) return;
    last.current = now;
    const layout = useLayout.getState().current;
    const scene = useScene.getState().scene;
    if (!layout || layout.positions.length !== scene.n * 3) return;
    camera.getWorldDirection(forward.current);
    const near = nearestInFront(layout.positions, camera.position, forward.current, max * 4, REACH).filter(
      (i) => PHOTO_CODES.has(scene.types[i]!),
    );
    const next: Planet[] = [];
    for (const index of near.slice(0, max)) {
      const id = scene.ids[index]!;
      const cached = cache.current.get(id);
      if (cached instanceof Texture) {
        next.push({ index, id, texture: cached });
        cache.current.delete(id); // most recently shown goes to the end of the eviction order
        cache.current.set(id, cached);
      } else if (cached === undefined) {
        cache.current.set(id, 'loading');
        api
          .thumbnail(id)
          .then((blob) => {
            const url = URL.createObjectURL(blob);
            new TextureLoader().load(
              url,
              (texture) => {
                URL.revokeObjectURL(url);
                if (!alive.current) return texture.dispose();
                texture.colorSpace = SRGBColorSpace;
                cache.current.set(id, texture);
              },
              undefined,
              () => {
                URL.revokeObjectURL(url);
                cache.current.set(id, 'missing'); // an unreadable thumbnail: it stays a point
              },
            );
          })
          .catch(() => cache.current.set(id, 'missing')); // no thumbnail (yet): it stays a point
      }
    }
    // Keep GPU memory bounded while flying past thousands of photos.
    const textures = [...cache.current].filter(([, t]) => t instanceof Texture).map(([k]) => k);
    for (const id of texturesToEvict(textures, new Set(next.map((p) => p.id)))) {
      const t = cache.current.get(id);
      if (t instanceof Texture) t.dispose();
      cache.current.delete(id);
    }
    setPlanets((prev) =>
      prev.length === next.length && prev.every((p, k) => p.id === next[k]!.id) ? prev : next,
    );
  });

  const layout = useLayout((s) => s.current);
  if (!layout) return null;
  return (
    <>
      {planets.map((p) => (
        <mesh
          key={p.id}
          position={[
            layout.positions[p.index * 3]!,
            layout.positions[p.index * 3 + 1]!,
            layout.positions[p.index * 3 + 2]!,
          ]}
        >
          <sphereGeometry args={[0.9, 24, 16]} />
          <meshBasicMaterial map={p.texture} />
        </mesh>
      ))}
    </>
  );
}
