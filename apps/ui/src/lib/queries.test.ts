import { describe, expect, it } from 'vitest';
import { itemShown } from './queries';

describe('the selected item', () => {
  it("is never the previous item's data kept while the new one loads", () => {
    const previous = { id: 'old', title: 'Old, in the trash' };
    // keepPreviousData hands back the old item under the new id: its actions would hit the new id.
    expect(itemShown('new', previous)).toBeUndefined();
    expect(itemShown('old', previous)).toBe(previous);
    expect(itemShown('new', undefined)).toBeUndefined();
  });
});
