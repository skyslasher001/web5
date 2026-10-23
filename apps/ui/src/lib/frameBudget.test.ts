import { describe, expect, it } from 'vitest';
import { median, nextSlowStreak, shouldGoSmooth } from './frameBudget';

const frames = (ms: number, n = 90) => Array.from({ length: n }, () => ms);

describe('frame budget', () => {
  it('needs two slow windows in a row', () => {
    let streak = nextSlowStreak(0, frames(33));
    expect(shouldGoSmooth(streak)).toBe(false);
    streak = nextSlowStreak(streak, frames(33));
    expect(shouldGoSmooth(streak)).toBe(true);
  });

  it('forgives a single hiccup and ignores hidden-window gaps', () => {
    expect(nextSlowStreak(1, frames(16.7))).toBe(0);
    expect(nextSlowStreak(0, [...frames(16.7, 80), ...frames(40, 10)])).toBe(0); // a short burst of slow frames
    expect(nextSlowStreak(1, [...frames(5000, 60), ...frames(33, 30)])).toBe(1); // mostly hidden: no verdict
    expect(median([3, 1, 2])).toBe(2);
  });
});
