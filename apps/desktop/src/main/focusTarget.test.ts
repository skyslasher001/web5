import { describe, expect, it } from 'vitest';
import { parseFocusTarget } from './focusTarget';

const id = '0192f0c4-7a3b-7c1d-9e2f-0123456789ab';

describe('focus targets from the command bar', () => {
  it('accepts items, galaxies and searches', () => {
    expect(parseFocusTarget({ kind: 'item', id })).toEqual({ kind: 'item', id });
    expect(parseFocusTarget({ kind: 'project', id, extra: 'dropped' })).toEqual({ kind: 'project', id });
    expect(parseFocusTarget({ kind: 'search', query: '  tax pdf  ' })).toEqual({
      kind: 'search',
      query: 'tax pdf',
    });
  });

  it('refuses anything else', () => {
    expect(parseFocusTarget(null)).toBeNull();
    expect(parseFocusTarget(id)).toBeNull();
    expect(parseFocusTarget({ kind: 'item', id: '../etc/passwd' })).toBeNull();
    expect(parseFocusTarget({ kind: 'item', id: id.toUpperCase() })).toBeNull();
    expect(parseFocusTarget({ kind: 'file', id })).toBeNull();
    expect(parseFocusTarget({ kind: 'search', query: '   ' })).toBeNull();
    expect(parseFocusTarget({ kind: 'search', query: 'x'.repeat(501) })).toBeNull();
    expect(parseFocusTarget({ kind: 'search', query: 42 })).toBeNull();
  });
});
