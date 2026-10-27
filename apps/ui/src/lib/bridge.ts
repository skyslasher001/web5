import type { UniverseBridge } from '@universe/shared-types';

export function bridge(): UniverseBridge {
  if (!window.universe) {
    throw new Error(
      'The desktop bridge is missing: open UNIVERSE through Electron (pnpm dev), not a browser.',
    );
  }
  return window.universe;
}
