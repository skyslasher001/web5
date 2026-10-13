import { describe, expect, it } from 'vitest';
import { staleQueriesFor } from './queryClient';

describe('engine query refresh', () => {
  it('maps events to the views they change', () => {
    expect(staleQueriesFor('approval.requested')).toContain('approvals');
    expect(staleQueriesFor('agent.step')).toEqual(['task']);
    expect(staleQueriesFor('agent.completed')).toEqual(expect.arrayContaining(['tasks', 'budget']));
    expect(staleQueriesFor('killswitch.engaged')).toContain('engine');
    expect(staleQueriesFor('memory.proposed')).toEqual(['memories']);
    expect(staleQueriesFor('item.created')).toEqual([]);
  });
});
