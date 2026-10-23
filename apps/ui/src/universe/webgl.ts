let available: boolean | null = null;

/**
 * True when this machine can create a WebGL2 context (no GPU or blocked drivers → false). Asked once, and the
 * probe context is released: the browser keeps only a few alive and drops the oldest (maybe the universe's).
 */
export function webglAvailable(): boolean {
  if (available !== null) return available;
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    available = !!gl;
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
  } catch {
    available = false;
  }
  return available;
}
