// The DOM layer over the canvas that holds labels and the hover tooltip. Scene components position
// their elements in it from the render loop (no React re-render per frame).
import { createContext, useContext, type RefObject } from 'react';

export const OverlayContext = createContext<RefObject<HTMLDivElement | null> | null>(null);

export function useOverlay(): RefObject<HTMLDivElement | null> | null {
  return useContext(OverlayContext);
}
