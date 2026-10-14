// Approvals waiting for you: an agent wants to do something the policy engine won't allow on its own.
import type { Approval } from '@universe/shared-types';
import { tokens } from '@universe/design-tokens';
import { useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, Wrench } from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { useApprovals, useForgeProposals } from '../lib/queries';
import { useUniverse } from '../state/store';
import { Button, Dot } from './ui';

const RISK_COLOR: Record<Approval['risk'], string> = {
  low: tokens.color.green,
  medium: tokens.color.amber,
  high: tokens.color.danger,
};

const SHOWN = 3;

function ApprovalCard({ approval }: { approval: Approval }) {
  const api = useApi();
  const client = useQueryClient();
  const agents = useUniverse((s) => s.agents);
  const selectTask = useUniverse((s) => s.selectTask);
  const [busy, setBusy] = useState(false);
  const agentId = approval.requester.replace(/^agent:/, '');
  const name = agents.find((a) => a.id === agentId)?.name ?? agentId;
  const decide = (approve: boolean, remember = false) => {
    setBusy(true);
    attempt(
      approve ? 'Approve' : 'Decline',
      api
        .decideApproval(approval.id, approve, remember)
        .then(() => client.invalidateQueries({ queryKey: ['approvals'] }))
        .finally(() => setBusy(false)),
    );
  };
  return (
    <li
      className="glass-strong hud-enter pointer-events-auto w-[26rem] max-w-[calc(100vw-2rem)] space-y-2 p-3"
      data-testid="approval"
    >
      <div className="flex items-center gap-2 text-xs text-ink-3">
        <Dot color={RISK_COLOR[approval.risk]} label={`${approval.risk} risk`} />
        <span className="font-medium text-ink-1">{name}</span>
        <span>asks to</span>
        <span className="font-mono text-ink-2">{approval.tool}</span>
      </div>
      <p className="text-sm text-ink-1" data-testid="approval-summary">
        {approval.summary}
      </p>
      <p className="text-xs leading-relaxed text-ink-3">{approval.reason}</p>
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Button tone="primary" disabled={busy} onClick={() => decide(true)} testid="approve">
          Approve
        </Button>
        <Button disabled={busy} onClick={() => decide(false)} testid="decline">
          Decline
        </Button>
        <Button
          disabled={busy}
          onClick={() => decide(true, true)}
          title={`Approve, and let ${name} use ${approval.tool} without asking from now on (a permission rule you can remove in Safety). Asks again after it has read untrusted content.`}
        >
          Always allow
        </Button>
        {approval.task_id && (
          <button
            type="button"
            onClick={() => selectTask(approval.task_id)}
            className="ml-auto text-xs text-ink-3 hover:text-accent"
          >
            View task
          </button>
        )}
      </div>
    </li>
  );
}

/** A Forge proposal waiting for you (SPEC §7: the tray holds tool calls and Forge patches). */
function ForgeCard({ id, title, risk }: { id: string; title: string; risk: string | null }) {
  return (
    <li
      className="glass pointer-events-auto flex w-[26rem] items-center gap-2 p-3 text-xs"
      data-testid="forge-card"
    >
      <Wrench className="size-4 shrink-0 text-amber" aria-hidden />
      <span className="flex-1">
        <span className="text-ink-3">Forge proposes a fix: </span>
        <span className="text-ink-1">{title}</span>
        {risk && <span className="text-ink-3"> · {risk} risk</span>}
      </span>
      <Button onClick={() => useUniverse.getState().openForge(id)} testid="forge-card-review">
        Review
      </Button>
    </li>
  );
}

export function ApprovalsTray() {
  const approvals = useApprovals();
  const proposals = useForgeProposals();
  const list = approvals.data ?? [];
  const ready = (proposals.data ?? []).filter((p) => p.status === 'ready');
  if (list.length === 0 && ready.length === 0) return null;
  return (
    <section
      aria-label="Approvals"
      className="absolute top-16 left-1/2 flex -translate-x-1/2 flex-col items-center gap-2"
      style={{ zIndex: 'var(--z-panel)' }}
    >
      <ul className="flex flex-col gap-2" aria-live="polite">
        {list.slice(0, SHOWN).map((a) => (
          <ApprovalCard key={a.id} approval={a} />
        ))}
        {ready.slice(0, 2).map((p) => (
          <ForgeCard key={p.id} id={p.id} title={p.title} risk={p.risk} />
        ))}
      </ul>
      {list.length > SHOWN && (
        <p className="glass pointer-events-auto flex items-center gap-1.5 px-3 py-1 text-xs text-ink-2">
          <ShieldAlert className="size-3.5" aria-hidden /> {list.length - SHOWN} more waiting
        </p>
      )}
    </section>
  );
}
