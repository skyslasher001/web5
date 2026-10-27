// Main only opens or reveals files inside the vault, whatever the renderer asks for.
import { realpathSync } from 'node:fs';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';

function within(root: string, target: string): boolean {
  const rel = relative(root, target);
  if (rel === '' || isAbsolute(rel)) return false;
  // '..notes.md' is a file in the vault; '..' or '../x' (or '..\x') is outside it.
  return rel !== '..' && !rel.startsWith(`..${sep}`) && !rel.startsWith('../');
}

/** The real path (links, junctions, mapped and subst drives, 8.3 names resolved), through the nearest existing
 * ancestor when the path itself doesn't exist. */
function real(path: string): string {
  const rest: string[] = [];
  let current = resolve(path);
  for (;;) {
    try {
      return join(realpathSync.native(current), ...rest);
    } catch {
      const parent = dirname(current);
      if (parent === current) return resolve(path);
      rest.unshift(basename(current));
      current = parent;
    }
  }
}

export function insideFolder(root: string, target: string): boolean {
  if (!isAbsolute(target)) return false;
  // Core sends resolved paths while the settings may hold a link (or the other way round): compare both forms.
  return within(resolve(root), resolve(target)) || within(real(root), real(target));
}
