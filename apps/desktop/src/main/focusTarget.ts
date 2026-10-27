// Validates what the command bar asks the main window to show: ids and a bounded query, nothing else.
import type { FocusTarget } from '@universe/shared-types';

const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAX_QUERY = 500;

export function parseFocusTarget(value: unknown): FocusTarget | null {
  if (typeof value !== 'object' || value === null) return null;
  const target = value as Record<string, unknown>;
  if (
    (target.kind === 'item' || target.kind === 'project') &&
    typeof target.id === 'string' &&
    ID.test(target.id)
  ) {
    return { kind: target.kind, id: target.id };
  }
  if (target.kind === 'search' && typeof target.query === 'string') {
    const query = target.query.trim();
    if (query && query.length <= MAX_QUERY) return { kind: 'search', query };
  }
  return null;
}
