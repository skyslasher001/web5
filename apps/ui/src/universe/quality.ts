// Quality presets (SPEC §7): Ultra, High, Balanced, Lite. Auto picks one from the graphics hardware, then the
// live frame budget steps it down if this machine can't keep up (and says so).

export type Quality = 'ultra' | 'high' | 'balanced' | 'lite';
export type QualitySetting = Quality | 'auto';
export const QUALITY_ORDER: Quality[] = ['ultra', 'high', 'balanced', 'lite'];

export interface Preset {
  label: string;
  /** Point size multiplier and the smallest on-screen size still drawn (level of detail). */
  pointScale: number;
  minPx: number;
  bloom: boolean;
  dpr: number | [number, number];
  labels: number;
  photoPlanets: number;
}

export const PRESETS: Record<Exclude<Quality, 'lite'>, Preset> = {
  ultra: {
    label: 'Ultra',
    pointScale: 1.1,
    minPx: 0.6,
    bloom: true,
    dpr: [1, 2],
    labels: 30,
    photoPlanets: 24,
  },
  high: {
    label: 'High',
    pointScale: 1,
    minPx: 1.0,
    bloom: true,
    dpr: [1, 1.5],
    labels: 20,
    photoPlanets: 16,
  },
  balanced: {
    label: 'Balanced',
    pointScale: 0.85,
    minPx: 1.8,
    bloom: false,
    dpr: 1,
    labels: 12,
    photoPlanets: 8,
  },
};

export const QUALITY_LABEL: Record<QualitySetting, string> = {
  auto: 'Auto',
  ultra: 'Ultra',
  high: 'High',
  balanced: 'Balanced',
  lite: 'Lite (2D)',
};

const SOFTWARE = /swiftshader|llvmpipe|softpipe|software|basic render|microsoft basic/i;
const DISCRETE = /nvidia|geforce|quadro|rtx|radeon\s*(rx|pro|vii)|\bamd\b.*\b(rx|pro)\b|arc\s*a\d/i;

/** The preset for this machine's graphics: software rendering → Lite, a discrete GPU → High, else Balanced. */
export function detectQuality(renderer: string | null, webgl: boolean): Quality {
  if (!webgl) return 'lite';
  if (!renderer) return 'balanced';
  if (SOFTWARE.test(renderer)) return 'lite';
  if (DISCRETE.test(renderer)) return 'high';
  return 'balanced';
}

let renderer: { name: string | null } | null = null;

/**
 * The GPU's name as WebGL reports it (null when the browser hides it). Asked once: each probe is a WebGL
 * context, and the browser keeps only a few alive (the oldest, maybe the universe's, is dropped).
 */
export function webglRenderer(): string | null {
  if (renderer) return renderer.name;
  let name: string | null = null;
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
    if (gl) {
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      name = ext
        ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL))
        : String(gl.getParameter(gl.RENDERER));
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    }
  } catch {
    name = null;
  }
  renderer = { name };
  return name;
}

/** One step down, never below Lite. */
export function stepDown(q: Quality): Quality {
  return QUALITY_ORDER[Math.min(QUALITY_ORDER.indexOf(q) + 1, QUALITY_ORDER.length - 1)]!;
}

const KEY = 'universe.quality';

export function loadQualitySetting(): QualitySetting {
  try {
    const value = localStorage.getItem(KEY);
    return value && (value === 'auto' || (QUALITY_ORDER as string[]).includes(value))
      ? (value as QualitySetting)
      : 'auto';
  } catch {
    return 'auto';
  }
}

export function saveQualitySetting(value: QualitySetting): void {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    // Storage unavailable (private window): the setting lasts for this session.
  }
}
