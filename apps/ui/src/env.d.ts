import type { UniverseBridge } from '@universe/shared-types';

declare global {
  interface Window {
    universe?: UniverseBridge;
  }
}
