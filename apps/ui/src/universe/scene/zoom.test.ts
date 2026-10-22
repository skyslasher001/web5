import { describe, expect, it } from 'vitest';
import {
  clipPlanes,
  distanceAt,
  easeToward,
  focusGalaxy,
  NOTCH,
  wheelFactor,
  zoomAnchor,
  zoomFraction,
  zoomGoal,
  zoomLimits,
} from './zoom';

describe('smooth zoom', () => {
  it('scales the distance by the same factor per notch, in and out', () => {
    expect(wheelFactor(100, 0, false)).toBeCloseTo(NOTCH);
    expect(wheelFactor(-100, 0, false)).toBeCloseTo(1 / NOTCH);
    // Lines and pages (mice and Windows settings that report them) land on the same scale.
    expect(wheelFactor(3, 1, false)).toBeCloseTo(wheelFactor(99, 0, false));
    // A runaway delta never jumps more than three notches.
    expect(wheelFactor(1e6, 0, false)).toBeCloseTo(NOTCH ** 3);
    expect(wheelFactor(-5, 2, false)).toBeCloseTo(NOTCH ** -3);
  });

  it('gives a touchpad pinch a finer scale', () => {
    const pinch = wheelFactor(-4, 0, true);
    expect(pinch).toBeLessThan(1);
    expect(pinch).toBeGreaterThan(wheelFactor(-100, 0, false));
  });

  it('eases on the log scale, independent of frame rate, and lands exactly on the goal', () => {
    // Zooming in ×10 and out ×10 take the same number of frames.
    let a = 100;
    let b = 10;
    let framesIn = 0;
    let framesOut = 0;
    for (; a !== 10 && framesIn < 1000; framesIn++) a = easeToward(a, 10, 1 / 60);
    for (; b !== 100 && framesOut < 1000; framesOut++) b = easeToward(b, 100, 1 / 60);
    expect(a).toBe(10);
    expect(framesIn).toBe(framesOut);
    expect(framesIn).toBeLessThan(60); // under a second at 60 FPS
    // Two 30 FPS frames get as far as four 60 FPS frames.
    const at30 = easeToward(easeToward(100, 10, 1 / 30), 10, 1 / 30);
    let at60 = 100;
    for (let k = 0; k < 4; k++) at60 = easeToward(at60, 10, 1 / 60);
    expect(at30).toBeCloseTo(at60, 6);
    // Reduced motion (an infinite rate) jumps straight there; a long stall never overshoots.
    expect(easeToward(100, 10, 1 / 60, Infinity)).toBe(10);
    expect(easeToward(100, 10, 30)).toBeGreaterThanOrEqual(10);
  });

  it('keeps the point under the pointer fixed while zooming', () => {
    const target = { x: 0, y: 0, z: 0 };
    const anchor = { x: 10, y: 0, z: -4 };
    const halfway = zoomAnchor(target, anchor, 0.5);
    expect(halfway).toEqual({ x: 5, y: 0, z: -2 });
    expect(zoomAnchor(target, anchor, 1)).toEqual(target);
    // Zooming back out by the inverse ratio returns to where it started.
    const back = zoomAnchor(halfway, anchor, 2);
    expect(back.x).toBeCloseTo(0);
    expect(back.z).toBeCloseTo(0);
  });

  it('keeps depth precision from one unit away to the whole universe', () => {
    const close = clipPlanes(1);
    const far = clipPlanes(6000);
    expect(close.near).toBeLessThan(0.1);
    expect(far.far).toBeGreaterThan(6000 * 2);
    expect(far.near).toBeGreaterThan(close.near);
    expect(close.far).toBeGreaterThan(6000); // the starfield stays visible up close
  });

  it('maps distance to a log-scale slider and back', () => {
    const { min, max } = zoomLimits(800);
    expect(max).toBe(4000);
    expect(zoomFraction(min, min, max)).toBe(0);
    expect(zoomFraction(max, min, max)).toBe(1);
    expect(distanceAt(zoomFraction(123, min, max), min, max)).toBeCloseTo(123);
    expect(zoomFraction(1e9, min, max)).toBe(1);
  });

  it('knows which galaxy the camera has zoomed into', () => {
    const centres = new Float32Array([0, 0, 0, 100, 0, 0]);
    const radii = new Float32Array([20, 10]);
    expect(focusGalaxy({ x: 2, y: 0, z: 0 }, 40, centres, radii)).toBe(0);
    expect(focusGalaxy({ x: 2, y: 0, z: 0 }, 400, centres, radii)).toBe(-1); // too far away to be "in" it
    expect(focusGalaxy({ x: 99, y: 0, z: 1 }, 20, centres, radii)).toBe(1);
    expect(focusGalaxy({ x: 50, y: 0, z: 0 }, 10, centres, radii)).toBe(-1); // between galaxies
  });
});

describe('zoom goals', () => {
  it('adds up wheel notches, but puts the slider exactly where it points while a zoom is in flight', () => {
    const { min, max } = { min: 1, max: 10_000 };
    // A zoom is gliding from 400 toward 100: another notch scales the goal, not the current distance.
    expect(zoomGoal({ by: 0.5 }, 100, 400, min, max)).toBe(50);
    // Dragging the slider to the middle (distance 100) lands on 100, however far the glide got.
    expect(zoomGoal({ to: 0.5 }, 100, 400, min, max)).toBeCloseTo(100);
    expect(zoomGoal({ to: 0.5 }, 25, 400, min, max)).toBeCloseTo(100);
    expect(zoomGoal({ to: 0.5 }, null, 400, min, max)).toBeCloseTo(100);
    expect(zoomGoal({ by: 1e9 }, null, 400, min, max)).toBe(max);
  });
});
