// Main only opens or reveals files inside the vault, whatever the renderer asks for.
import { isAbsolute, relative, resolve } from 'node:path';

export function insideFolder(root: string, target: string): boolean {
  if (!isAbsolute(target)) return false;
  const rel = relative(resolve(root), resolve(target));
  return rel !== '' && !rel.startsWith('..') && !isAbsolute(rel);
}
