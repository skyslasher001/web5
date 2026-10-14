// d3-force-3d (MIT) ships no types; this is the small part of its API the Graph layout uses.
declare module 'd3-force-3d' {
  interface Force {
    (alpha: number): void;
  }
  interface LinkForce<L> extends Force {
    distance(d: number): LinkForce<L>;
    strength(s: number | ((link: L) => number)): LinkForce<L>;
  }
  interface ManyBodyForce extends Force {
    strength(s: number): ManyBodyForce;
    theta(t: number): ManyBodyForce;
    distanceMax(d: number): ManyBodyForce;
  }
  interface PositionForce extends Force {
    strength(s: number): PositionForce;
  }
  interface Simulation {
    force(name: string, force: Force): Simulation;
    stop(): Simulation;
    tick(iterations?: number): Simulation;
  }
  export function forceSimulation<N>(nodes: N[], dimensions?: number): Simulation;
  export function forceLink<L>(links: L[]): LinkForce<L>;
  export function forceManyBody(): ManyBodyForce;
  export function forceX(x?: number): PositionForce;
  export function forceY(y?: number): PositionForce;
  export function forceZ(z?: number): PositionForce;
}
