// The tray icon, drawn in code (no image asset): an accent-coloured ring with a core dot.

const ACCENT = { r: 0x3e, g: 0xe0, b: 0xff };

/** BGRA pixels for a ring + dot, anti-aliased by distance. */
export function ringPixels(size: number): Buffer {
  const buf = Buffer.alloc(size * size * 4);
  const c = (size - 1) / 2;
  const outer = size * 0.46;
  const inner = size * 0.32;
  const dot = size * 0.14;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const d = Math.hypot(x - c, y - c);
      const ring = Math.max(0, Math.min(1, outer - d + 0.5)) * Math.max(0, Math.min(1, d - inner + 0.5));
      const core = Math.max(0, Math.min(1, dot - d + 0.5));
      const alpha = Math.max(ring, core);
      const i = (y * size + x) * 4;
      buf[i] = ACCENT.b;
      buf[i + 1] = ACCENT.g;
      buf[i + 2] = ACCENT.r;
      buf[i + 3] = Math.round(alpha * 255);
    }
  }
  return buf;
}
