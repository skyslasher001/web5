// One draw call for every item (ADR-0012): each point draws its type's shape procedurally, so colour is
// always paired with a shape. Layout changes blend two position buffers on the GPU (uMix 0 → 1).

const SHARED_VERTEX = /* glsl */ `
  attribute vec3 aFrom;
  attribute float aSize;
  attribute float aCreated;
  attribute float aState;
  attribute float aHidden;
  uniform float uMix;
  uniform float uScale;
  uniform float uSizeMul;
  uniform float uTimeCut;
  uniform float uMinPx;

  // Level of detail: an item smaller than uMinPx on screen fades out over a short band, then isn't drawn
  // (its galaxy's sprite stands in for it from afar), so zooming never makes stars pop. Search results are
  // always drawn.
  const float FADE_FROM = 0.7;                         // fully gone at 70 % of uMinPx

  float rawSize(vec4 mv) {
    return aSize * uSizeMul * (1.0 + step(0.5, aState) * 0.8) * uScale / -mv.z;
  }

  float lodFade(float raw) {
    return step(0.5, aState) > 0.5 ? 1.0 : smoothstep(uMinPx * FADE_FROM, uMinPx, raw);
  }

  float pointSize(float raw) {
    float hidden = step(uTimeCut, aCreated);           // created after the time slider: not born yet
    if (hidden > 0.5 || aHidden > 0.5 || lodFade(raw) <= 0.0) return 0.0;
    return clamp(raw, 1.5, 44.0);
  }

  // Culled points go outside the clip volume, so the rasterizer never sees them.
  vec4 clipped(vec4 mv, float size) {
    return size > 0.0 ? projectionMatrix * mv : vec4(2.0, 2.0, 2.0, 1.0);
  }

  vec3 placed() { return mix(aFrom, position, uMix); }
`;

export const POINT_VERTEX = /* glsl */ `
  ${SHARED_VERTEX}
  attribute vec3 aColor;
  attribute float aShape;
  attribute float aGlow;
  attribute float aSeed;
  uniform float uDim;
  varying vec3 vColor;
  varying float vShape;
  varying float vGlow;
  varying float vSeed;

  void main() {
    vec4 mv = modelViewMatrix * vec4(placed(), 1.0);
    float raw = rawSize(mv);
    gl_PointSize = pointSize(raw);
    gl_Position = clipped(mv, gl_PointSize);
    float highlighted = step(0.5, aState);
    vColor = aColor;
    vShape = aShape;
    vSeed = aSeed;
    // A search dims everything that isn't a result; distance fades what's about to drop out of detail.
    vGlow = aGlow * mix(1.0 - uDim * 0.88, 1.0, highlighted) * lodFade(raw);
  }
`;

export const POINT_FRAGMENT = /* glsl */ `
  uniform float uTime;
  varying vec3 vColor;
  varying float vShape;
  varying float vGlow;
  varying float vSeed;

  float disc(float r, float edge) { return 1.0 - smoothstep(edge - 0.06, edge, r); }

  void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    c.y = -c.y;
    float r = length(c);
    if (r > 1.0) discard;
    float a = 0.0;
    vec3 col = vColor;
    int shape = int(vShape + 0.5);
    if (shape == 0) {                                   // star: hot core, soft glow, four spikes
      a = disc(r, 0.22) + exp(-r * r * 9.0) * 0.55;
      a += (max(0.0, 1.0 - abs(c.x) * 14.0) + max(0.0, 1.0 - abs(c.y) * 14.0)) * (1.0 - r) * 0.45;
      col = mix(col, vec3(1.0), disc(r, 0.12) * 0.7);
    } else if (shape == 1) {                            // planet: a lit sphere with a thin ring
      float body = disc(r, 0.58);
      vec3 n = vec3(c / 0.58, sqrt(max(0.0, 1.0 - dot(c, c) / 0.3364)));
      float light = clamp(dot(n, normalize(vec3(-0.5, 0.6, 0.6))), 0.15, 1.0);
      float ring = (1.0 - smoothstep(0.0, 0.05, abs(length(c * vec2(1.0, 3.2)) - 0.86))) * step(0.58, r);
      a = body + ring * 0.6;
      col = col * mix(1.0, light * 1.3, body);
    } else if (shape == 2) {                            // pulsar: core plus an expanding ring
      float wave = fract(uTime * 0.7 + vSeed);
      a = disc(r, 0.2) + (1.0 - smoothstep(0.0, 0.08, abs(r - wave * 0.95))) * (1.0 - wave) * 0.9;
      a += exp(-r * r * 12.0) * 0.4;
    } else if (shape == 3) {                            // moon / asteroid: a small grey-tinted body
      float body = disc(r, 0.42);
      vec2 crater = c - vec2(0.12, 0.1) * (0.5 + vSeed);
      float pits = (1.0 - smoothstep(0.0, 0.1, length(crater))) * 0.35;
      a = body;
      col = mix(vec3(0.62, 0.66, 0.75), col, 0.55) * (1.0 - pits);
    } else if (shape == 4) {                            // space station: frame, cross and a status light
      vec2 q = abs(c);
      float frame = step(max(q.x, q.y), 0.42) * (1.0 - step(max(q.x, q.y), 0.3));
      float cross = step(min(q.x, q.y), 0.06) * step(max(q.x, q.y), 0.6);
      float light = disc(length(c - vec2(0.0, 0.62)), 0.13) * (0.6 + 0.4 * sin(uTime * 3.0 + vSeed * 6.0));
      a = max(max(frame, cross), light);
      col = mix(col, vec3(0.36, 0.89, 0.61), light);
    } else if (shape == 5) {                            // satellite: a body with two solar panels
      vec2 q = abs(c);
      float body = step(q.x + q.y, 0.24);
      float panels = step(0.32, q.x) * step(q.x, 0.8) * step(q.y, 0.12);
      a = max(body, panels * 0.8);
    } else if (shape == 6) {                            // nebula: a soft, slowly turning cloud
      float ang = atan(c.y, c.x);
      float swirl = 0.65 + 0.35 * sin(ang * 3.0 + uTime * 0.3 + vSeed * 6.28 + r * 6.0);
      a = exp(-r * r * 3.2) * swirl * 0.7;
    } else {                                            // protostar: a cloud with a bright core forming
      a = exp(-r * r * 3.5) * 0.5 + disc(r, 0.16) * 0.9;
    }
    a *= vGlow;
    if (a < 0.02) discard;
    gl_FragColor = vec4(col * a, a);
  }
`;

/** The picking pass: the same points, each painted with its index as a colour (GPU picking). */
export const PICK_VERTEX = /* glsl */ `
  ${SHARED_VERTEX}
  attribute vec3 aPick;
  varying vec3 vPick;
  void main() {
    vec4 mv = modelViewMatrix * vec4(placed(), 1.0);
    float raw = rawSize(mv);
    float size = lodFade(raw) >= 1.0 ? pointSize(raw) : 0.0; // half-faded items aren't clickable yet
    gl_PointSize = max(size, 6.0);                      // small items you can see stay easy to click
    gl_Position = clipped(mv, size);
    vPick = aPick;
  }
`;

export const PICK_FRAGMENT = /* glsl */ `
  varying vec3 vPick;
  void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    if (dot(c, c) > 0.85) discard;
    gl_FragColor = vec4(vPick, 1.0);
  }
`;

/** Index ↔ pick colour (24 bits: 16 million items; 0 means nothing). */
export function pickColor(index: number): [number, number, number] {
  const id = index + 1;
  return [(id & 255) / 255, ((id >> 8) & 255) / 255, ((id >> 16) & 255) / 255];
}

export function pickIndex(r: number, g: number, b: number): number {
  return (r | (g << 8) | (b << 16)) - 1;
}
