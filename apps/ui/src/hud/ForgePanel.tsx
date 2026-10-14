// Forge (SPEC §9, ADR-0014): report a problem, see what's broken, let Forge fix it, and decide on its proposals.
// Approving opens a native dialog in Electron main (renderer code can't click it); the supervisor then applies,
// watches for 30 minutes and rolls back on its own if something breaks.
import type { ForgeIssue, ForgeProposal } from '@universe/shared-types';
import { tokens } from '@universe/design-tokens';
import { useQueryClient } from '@tanstack/react-query';
import { Check, ChevronDown, ChevronRight, Hammer, ShieldCheck, ShieldX, Wrench, X } from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { timeAgo } from '../lib/format';
import { useForgeIssues, useForgeProposals, useForgeStatus } from '../lib/queries';
import { useUniverse } from '../state/store';
import { Button, Dot, inputClass, Section } from './ui';

const STATUS_COLOR: Record<ForgeProposal['status'], string> = {
  draft: tokens.color.slate,
  verifying: tokens.color.accent,
  failed: tokens.color.danger,
  ready: tokens.color.amber,
  approved: tokens.color.accent,
  applied: tokens.color.green,
  rolled_back: tokens.color.slate,
  rejected: tokens.color.slate,
};

const STATUS_LABEL: Record<ForgeProposal['status'], string> = {
  draft: 'working',
  verifying: 'verifying',
  failed: 'blocked',
  ready: 'waiting for you',
  approved: 'approved',
  applied: 'applied',
  rolled_back: 'rolled back',
  rejected: 'rejected',
};

function useRefresh() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ['forge'] });
}

/** A unified diff, coloured by line. */
export function DiffView({ diff }: { diff: string }) {
  return (
    <pre
      className="max-h-80 overflow-auto rounded-md bg-space-0/80 p-2 font-mono text-[10.5px] leading-snug"
      data-testid="proposal-diff"
    >
      {diff.split('\n').map((line, k) => {
        const color = line.startsWith('+++') || line.startsWith('---')
          ? tokens.color.ink['3']
          : line.startsWith('+')
            ? tokens.color.green
            : line.startsWith('-')
              ? tokens.color.danger
              : line.startsWith('@@')
                ? tokens.color.violet
                : tokens.color.ink['2']; // prettier-ignore
        return (
          <div key={k} style={{ color }}>
            {line || ' '}
          </div>
        );
      })}
    </pre>
  );
}

function Verification({ p }: { p: ForgeProposal }) {
  const v = p.verification as {
    passed?: boolean;
    repro?: { test?: string; fails_on_base?: boolean; passes_on_head?: boolean };
    checks?: { name: string; ok: boolean; seconds: number }[];
  };
  if (!v.repro) return <p className="text-ink-3">Not verified yet.</p>;
  const mark = (ok: boolean | undefined) => (ok ? '✓' : '✗');
  return (
    <ul className="space-y-0.5 font-mono text-[11px]" data-testid="proposal-verification">
      <li>
        {mark(v.repro.fails_on_base)} the test fails on the old code ({v.repro.test})
      </li>
      <li>{mark(v.repro.passes_on_head)} and passes with the fix</li>
      {(v.checks ?? []).map((c) => (
        <li key={c.name} style={{ color: c.ok ? undefined : tokens.color.danger }}>
          {mark(c.ok)} {c.name} · {c.seconds.toFixed(1)} s
        </li>
      ))}
    </ul>
  );
}

function Reviews({ p }: { p: ForgeProposal }) {
  const r = p.reviews as {
    critic?: { output?: string | null };
    sentinel?: {
      available?: boolean;
      reason?: string;
      verdict?: string;
      findings?: { detail: string; file: string }[];
    };
  };
  const s = r.sentinel;
  return (
    <div className="space-y-1" data-testid="proposal-reviews">
      <p>
        <span className="text-ink-3">Critic: </span>
        {r.critic?.output ?? 'no review'}
      </p>
      <p className="flex items-start gap-1">
        {s?.available && s.verdict === 'pass' ? (
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-green" aria-hidden />
        ) : (
          <ShieldX className="mt-0.5 size-3.5 shrink-0 text-amber" aria-hidden />
        )}
        <span>
          <span className="text-ink-3">Sentinel: </span>
          {s?.available ? (s.verdict === 'pass' ? 'passed' : 'blocked it') : (s?.reason ?? 'no review')}
        </span>
      </p>
      {(s?.findings ?? []).map((f, k) => (
        <p key={k} className="pl-4 text-ink-3">
          • {f.detail} {f.file && <span className="font-mono">({f.file})</span>}
        </p>
      ))}
    </div>
  );
}

function ProposalCard({ p, open, onToggle }: { p: ForgeProposal; open: boolean; onToggle: () => void }) {
  const api = useApi();
  const refresh = useRefresh();
  const [busy, setBusy] = useState(false);
  const approve = () => {
    const bridge = window.universe;
    if (!bridge) return;
    setBusy(true);
    attempt(
      'Approve',
      bridge
        .forgeApprove(p.id)
        .then((d) => {
          useUniverse.getState().addNotice(d.ok ? 'good' : 'info', d.message);
          return refresh();
        })
        .finally(() => setBusy(false)),
    );
  };
  const reject = () => attempt('Reject', api.forgeReject(p.id).then(refresh));
  const live =
    p.status === 'ready' || p.status === 'draft' || p.status === 'verifying' || p.status === 'failed';
  return (
    <li className="rounded-md border border-hairline-1 text-xs" data-testid="proposal" data-status={p.status}>
      <button type="button" onClick={onToggle} className="flex w-full items-center gap-2 p-2 text-left">
        {open ? (
          <ChevronDown className="size-3.5" aria-hidden />
        ) : (
          <ChevronRight className="size-3.5" aria-hidden />
        )}
        <Dot color={STATUS_COLOR[p.status]} pulse={p.status === 'verifying'} label={STATUS_LABEL[p.status]} />
        <span className="flex-1 truncate text-ink-1">{p.title}</span>
        <span className="text-[11px] text-ink-3" data-testid="proposal-status">
          {STATUS_LABEL[p.status]}
          {p.risk && ` · ${p.risk} risk`}
        </span>
      </button>
      {open && (
        <div className="space-y-2.5 border-t border-hairline-1 p-2.5">
          {p.root_cause && (
            <p>
              <span className="text-ink-3">Why it broke: </span>
              {p.root_cause}
            </p>
          )}
          <Verification p={p} />
          <Reviews p={p} />
          {p.files.length > 0 && (
            <p className="font-mono text-[11px] text-ink-3">
              {p.files.map((f) => `${f.status} ${f.path}`).join(' · ')}
            </p>
          )}
          {p.diff && <DiffView diff={p.diff} />}
          {p.rollback_plan && <p className="text-ink-3">Rollback: {p.rollback_plan}</p>}
          <p className="text-[11px] text-ink-3">
            {p.release ? `Release ${p.release} · ` : ''}
            {p.diff_sha ? `change ${p.diff_sha.slice(0, 12)} · ` : ''}
            {timeAgo(p.created_at)}
          </p>
          {live && (
            <div className="flex gap-1">
              {p.status === 'ready' && (
                <Button tone="primary" onClick={approve} disabled={busy} testid="proposal-approve">
                  <Check className="size-3.5" aria-hidden /> Approve…
                </Button>
              )}
              <Button onClick={reject} disabled={busy} testid="proposal-reject">
                <X className="size-3.5" aria-hidden /> Reject
              </Button>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function IssueRow({ issue, canFix }: { issue: ForgeIssue; canFix: boolean }) {
  const api = useApi();
  const refresh = useRefresh();
  const fix = () =>
    attempt(
      'Ask Forge',
      api.forgeFix(issue.id).then((r) => {
        useUniverse.getState().addNotice('info', 'Forge is on it: follow it in Agents → Tasks');
        useUniverse.getState().selectTask(r.task_id);
        return refresh();
      }),
    );
  return (
    <li className="space-y-1 rounded-md border border-hairline-1 p-2 text-xs" data-testid="forge-issue">
      <div className="flex items-start gap-2">
        <Dot
          color={issue.severity === 'critical' ? tokens.color.danger : tokens.color.amber}
          label={issue.severity}
        />
        <span className="flex-1 text-ink-1">{issue.title}</span>
      </div>
      <p className="text-[11px] text-ink-3">
        {issue.source} · seen {issue.count}× · {issue.status} · last {timeAgo(issue.last_seen)}
      </p>
      {issue.status === 'open' && (
        <div className="flex gap-1">
          <Button
            onClick={fix}
            disabled={!canFix}
            testid="forge-fix"
            title={canFix ? undefined : 'Forge isn’t installed'}
          >
            <Wrench className="size-3" aria-hidden /> Fix it
          </Button>
          <Button onClick={() => attempt('Ignore', api.forgeIgnore(issue.id).then(refresh))}>Ignore</Button>
        </div>
      )}
    </li>
  );
}

export function ForgePanel() {
  const api = useApi();
  const refresh = useRefresh();
  const status = useForgeStatus();
  const issues = useForgeIssues();
  const proposals = useForgeProposals();
  const focus = useUniverse((s) => s.forgeFocus);
  const [open, setOpen] = useState<string | null>(focus);
  const [report, setReport] = useState('');
  const s = status.data;
  const canFix = !!s?.available && !!s.agent;
  const send = () => {
    const text = report.trim();
    if (text.length < 5) return;
    attempt(
      'Report',
      api.forgeReport(text).then(() => {
        setReport('');
        return refresh();
      }),
    );
  };
  const missing = s ? [s.reason, s.agent_reason, s.sentinel_reason].filter(Boolean) : [];
  return (
    <div className="space-y-4" data-testid="forge-panel">
      {missing.length > 0 && (
        <div
          className="space-y-1 rounded-md border border-amber/40 bg-amber/10 p-2 text-xs"
          data-testid="forge-missing"
        >
          {missing.map((m) => (
            <p key={m}>{m}</p>
          ))}
        </div>
      )}
      <Section title="Report a problem">
        <textarea
          value={report}
          onChange={(e) => setReport(e.target.value)}
          rows={2}
          placeholder="The photo viewer froze when I opened a PDF…"
          aria-label="Describe the problem"
          className={`${inputClass} w-full resize-none`}
          data-testid="forge-report"
        />
        <Button onClick={send} disabled={report.trim().length < 5} testid="forge-report-send">
          <Hammer className="size-3.5" aria-hidden /> Report to Forge
        </Button>
      </Section>
      <Section
        title={`Proposals${s ? ` · ${s.proposals_today} of ${s.daily_cap} today` : ''}`}
        testid="forge-proposals"
      >
        {proposals.data?.length === 0 && <p className="text-xs text-ink-3">No proposals yet.</p>}
        <ul className="space-y-2">
          {proposals.data?.map((p) => (
            <ProposalCard
              key={p.id}
              p={p}
              open={open === p.id}
              onToggle={() => setOpen(open === p.id ? null : p.id)}
            />
          ))}
        </ul>
      </Section>
      <Section title="Issues" testid="forge-issues">
        {issues.data?.length === 0 && (
          <p className="text-xs text-ink-3">Nothing broken that Forge knows about.</p>
        )}
        <ul className="space-y-2">
          {issues.data?.map((i) => (
            <IssueRow key={i.id} issue={i} canFix={canFix} />
          ))}
        </ul>
      </Section>
    </div>
  );
}
