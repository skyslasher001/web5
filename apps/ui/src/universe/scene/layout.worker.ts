// Computes the Project, Time and Graph layouts off the main thread (SPEC §7: layouts never block the UI).
import { graphLayout, projectLayout, timeLayout, type LayoutInput, type LayoutResult } from './layouts';

export type LayoutKind = 'project' | 'time' | 'graph';

export interface LayoutRequest {
  id: number;
  kind: LayoutKind;
  input: LayoutInput;
}

export interface LayoutResponse {
  id: number;
  kind: LayoutKind;
  result: LayoutResult;
  ms: number;
}

const compute: Record<LayoutKind, (input: LayoutInput) => LayoutResult> = {
  project: projectLayout,
  time: timeLayout,
  graph: graphLayout,
};

self.onmessage = (event: MessageEvent<LayoutRequest>) => {
  const { id, kind, input } = event.data;
  const started = performance.now();
  const result = compute[kind](input);
  const response: LayoutResponse = { id, kind, result, ms: Math.round(performance.now() - started) };
  (self as unknown as Worker).postMessage(response, [
    result.positions.buffer,
    result.galaxyCentres.buffer,
    result.galaxyRadii.buffer,
  ]);
};
