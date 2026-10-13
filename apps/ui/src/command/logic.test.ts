import type { ItemSummary, RecallResult, SearchHit } from '@universe/shared-types';
import { describe, expect, it } from 'vitest';
import { actionForRecall, actionForRow, parseCapture, rowsFor } from './logic';

function hit(id: string, title = id): SearchHit {
  return { item: { id, title } as ItemSummary, score: 1, snippet: null, matched: ['title'] };
}

function recall(partial: Partial<RecallResult>): RecallResult {
  return {
    intent: 'search',
    action: 'show_results',
    confidence: 0,
    target_id: null,
    parsed: { text: '', types: [], project_ids: [], date_from: null, date_to: null, chips: [] },
    hits: [],
    semantic: false,
    took_ms: 1,
    ...partial,
  } as RecallResult;
}

describe('command bar rows', () => {
  it('ends with saving the text as a note', () => {
    const rows = rowsFor('  tax return ', [hit('a'), hit('b')]);
    expect(rows.map((r) => r.kind)).toEqual(['hit', 'hit', 'capture']);
    expect(rows.at(-1)).toEqual({ kind: 'capture', text: 'tax return' });
    expect(rowsFor('   ', [])).toEqual([]);
  });

  it('opens a picked item, or shows it in UNIVERSE with Ctrl+Enter', () => {
    const row = rowsFor('x', [hit('a')])[0]!;
    expect(actionForRow(row, false)).toEqual({ kind: 'open', itemId: 'a' });
    expect(actionForRow(row, true)).toEqual({ kind: 'focus', target: { kind: 'item', id: 'a' } });
    expect(actionForRow({ kind: 'capture', text: 'idea' }, false)).toEqual({ kind: 'capture', text: 'idea' });
  });
});

describe('Enter without a picked row', () => {
  it('follows the recall intent', () => {
    expect(
      actionForRecall(recall({ intent: 'go_to', action: 'show_project', target_id: 'p1' }), 'go to work'),
    ).toEqual({
      kind: 'focus',
      target: { kind: 'project', id: 'p1' },
    });
    expect(
      actionForRecall(
        recall({ intent: 'open', action: 'open_item', target_id: 'i1', hits: [hit('i1')] }),
        'open budget',
      ),
    ).toEqual({ kind: 'open', itemId: 'i1' });
    expect(actionForRecall(recall({ intent: 'show', hits: [hit('a')] }), 'show photos from may')).toEqual({
      kind: 'focus',
      target: { kind: 'search', query: 'show photos from may' },
    });
  });

  it('opens the top hit of a plain search, and says so when nothing matches', () => {
    expect(actionForRecall(recall({ hits: [hit('a'), hit('b')] }), 'budget')).toEqual({
      kind: 'open',
      itemId: 'a',
    });
    // A low-confidence "open …" doesn't guess past the top hit either.
    expect(actionForRecall(recall({ intent: 'open', hits: [hit('b')] }), 'open thing')).toEqual({
      kind: 'open',
      itemId: 'b',
    });
    expect(actionForRecall(recall({}), 'zzz').kind).toBe('none');
  });
});

describe('quick capture', () => {
  it('turns hashtags into tags and keeps the text as written', () => {
    expect(parseCapture('  Call the bank #Finance #todo about #finance\n')).toEqual({
      text: 'Call the bank #Finance #todo about #finance',
      tags: ['finance', 'todo'],
    });
    expect(parseCapture('issue#12 and C# are not tags').tags).toEqual([]);
    expect(parseCapture('#idée works').tags).toEqual(['idée']);
  });
});
