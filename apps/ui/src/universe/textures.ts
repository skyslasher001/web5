// Procedural sprite textures (generated once on a 2D canvas, no image assets).
import { CanvasTexture, SRGBColorSpace } from 'three';

function canvas(size: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  return [c, c.getContext('2d')!];
}

function finish(c: HTMLCanvasElement): CanvasTexture {
  const texture = new CanvasTexture(c);
  texture.colorSpace = SRGBColorSpace;
  return texture;
}

export function glowTexture(color: string, size = 256): CanvasTexture {
  const [c, ctx] = canvas(size);
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, '#ffffff');
  g.addColorStop(0.12, color);
  g.addColorStop(0.4, `${color}55`);
  g.addColorStop(1, `${color}00`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return finish(c);
}

/** A small spiral galaxy: two logarithmic arms of dots around a bright core. Deterministic per seed. */
export function galaxyTexture(color: string, seed: number, size = 512): CanvasTexture {
  const [c, ctx] = canvas(size);
  let state = seed * 9301 + 49297;
  const rand = () => {
    state = (state * 9301 + 49297) % 233280;
    return state / 233280;
  };
  const center = size / 2;
  const halo = ctx.createRadialGradient(center, center, 0, center, center, center);
  halo.addColorStop(0, `${color}66`);
  halo.addColorStop(0.35, `${color}22`);
  halo.addColorStop(1, `${color}00`);
  ctx.fillStyle = halo;
  ctx.fillRect(0, 0, size, size);
  const twist = 2.6 + rand() * 1.2;
  for (let arm = 0; arm < 2; arm++) {
    for (let i = 0; i < 900; i++) {
      const t = rand();
      const angle = t * twist * Math.PI + arm * Math.PI + (rand() - 0.5) * 0.5;
      const radius = t * center * 0.85 + (rand() - 0.5) * 14;
      const x = center + Math.cos(angle) * radius;
      const y = center + Math.sin(angle) * radius * 0.62;
      const r = (1 - t) * 1.8 + rand() * 0.9;
      ctx.globalAlpha = 0.25 + (1 - t) * 0.6;
      ctx.fillStyle = rand() > 0.85 ? '#ffffff' : color;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.globalAlpha = 1;
  const core = ctx.createRadialGradient(center, center, 0, center, center, size * 0.12);
  core.addColorStop(0, '#ffffff');
  core.addColorStop(0.3, color);
  core.addColorStop(1, `${color}00`);
  ctx.fillStyle = core;
  ctx.fillRect(0, 0, size, size);
  return finish(c);
}
