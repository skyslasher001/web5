import { describe, expect, it } from 'vitest';
import { queryString } from './api';
import { sameTypes, splitMarks, TYPE_CHIPS } from './itemTypes';

describe('search snippets', () => {
  it('splits «marked» matches for highlighting', () => {
    expect(splitMarks('…the «lake» house by the «lake»')).toEqual([
      { text: '…the ', mark: false },
      { text: 'lake', mark: true },
      { text: ' house by the ', mark: false },
      { text: 'lake', mark: true },
    ]);
    expect(splitMarks('no matches')).toEqual([{ text: 'no matches', mark: false }]);
  });
});

describe('type chips', () => {
  it('compare as sets', () => {
    expect(sameTypes(['photo', 'screenshot'], ['screenshot', 'photo'])).toBe(true);
    expect(sameTypes(['photo'], ['photo', 'screenshot'])).toBe(false);
    expect(new Set(TYPE_CHIPS.flatMap((c) => c.types)).size).toBe(TYPE_CHIPS.flatMap((c) => c.types).length);
  });
});

describe('query strings', () => {
  it('repeat array keys and drop empty values', () => {
    expect(
      queryString({ q: 'lake house', type: ['photo', 'pdf'], project: null, limit: 30, cursor: '' }),
    ).toBe('?q=lake+house&type=photo&type=pdf&limit=30');
    expect(queryString({})).toBe('');
  });
});
