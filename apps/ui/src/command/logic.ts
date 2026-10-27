// The command bar's decisions, kept pure so they're unit-tested (SPEC §6: the recall fast path).
import type { FocusTarget, RecallResult, SearchHit } from '@universe/shared-types';

/** One row in the result list: a found item, or saving what was typed as a note. */
export type Row = { kind: 'hit'; hit: SearchHit } | { kind: 'capture'; text: string };

export type BarAction =
  | { kind: 'open'; itemId: string }
  | { kind: 'focus'; target: FocusTarget }
  | { kind: 'capture'; text: string }
  | { kind: 'none'; message: string };

export function rowsFor(query: string, hits: SearchHit[]): Row[] {
  const rows: Row[] = hits.map((hit) => ({ kind: 'hit', hit }));
  if (query.trim()) rows.push({ kind: 'capture', text: query.trim() });
  return rows;
}

/** Enter on a row the user picked with the arrow keys. Ctrl+Enter shows it in UNIVERSE instead of opening it. */
export function actionForRow(row: Row, reveal: boolean): BarAction {
  if (row.kind === 'capture') return { kind: 'capture', text: row.text };
  const id = row.hit.item.id;
  return reveal ? { kind: 'focus', target: { kind: 'item', id } } : { kind: 'open', itemId: id };
}

/**
 * The row Enter runs: the highlighted one when it was picked with the arrows or Ctrl+Enter asks to show it,
 * else null (the recall grammar decides). `fresh` is false while the list still holds the previous query's
 * hits (the new search hasn't answered): those hits are never run, only the capture row (always current).
 */
export function rowForEnter(
  rows: Row[],
  active: number,
  picked: boolean,
  reveal: boolean,
  fresh: boolean,
): Row | null {
  const row = rows[active];
  if (!row || !(picked || reveal)) return null;
  return row.kind === 'hit' && !fresh ? null : row;
}

/** Enter without picking a row: what the recall grammar understood ("open …", "go to …", "show …"). */
export function actionForRecall(result: RecallResult, query: string): BarAction {
  if (result.action === 'show_project' && result.target_id) {
    return { kind: 'focus', target: { kind: 'project', id: result.target_id } };
  }
  if (result.action === 'open_item' && result.target_id) return { kind: 'open', itemId: result.target_id };
  if (result.intent === 'show') return { kind: 'focus', target: { kind: 'search', query } };
  const top = result.hits[0];
  if (top) return { kind: 'open', itemId: top.item.id };
  return { kind: 'none', message: 'Nothing found. Ctrl+S saves what you typed as a note.' };
}

export interface CaptureDraft {
  text: string;
  tags: string[];
}

const TAG = /(?:^|\s)#([\p{L}\p{N}_-]{1,60})(?=\s|$)/gu;

/** Hashtags in a quick capture become tags; the text keeps them so the note reads as written. */
export function parseCapture(raw: string): CaptureDraft {
  const text = raw.trim();
  const tags = new Set<string>();
  for (const match of text.matchAll(TAG)) tags.add(match[1]!.toLowerCase());
  return { text, tags: [...tags].slice(0, 50) };
}
