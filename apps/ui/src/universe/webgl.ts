/** True when this machine can create a WebGL2 context (no GPU or blocked drivers → false). */
export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return !!canvas.getContext('webgl2');
  } catch {
    return false;
  }
}
