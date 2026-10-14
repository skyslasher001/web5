// The agent engine: run a task, follow its trace, look after what agents remember, and manage the roster
// (every agent with its synopsis and stats; add, turn off, remove).
import type { AgentTask, Memory, TaskStep } from '@universe/shared-types';
import { tokens } from '@universe/design-tokens';
import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, Pencil, Play, Square, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { timeAgo } from '../lib/format';
import { useEngine, useMemories, useTask, useTasks } from '../lib/queries';
import { useUniverse } from '../state/store';
import { AgentRoster } from './AgentRoster';
import { Button, Dot, inputClass, Section } from './ui';

const STATUS_COLOR: Record<AgentTask['status'], string> = {
  queued: tokens.color.slate,
  running: tokens.color.accent,
  waiting_approval: tokens.color.amber,
  done: tokens.color.green,
  failed: tokens.color.danger,
  cancelled: tokens.color.slate,
};

const STATUS_LABEL: Record<AgentTask['status'], string> = {
  queued: 'queued',
  running: 'running',
  waiting_approval: 'waiting for you',
  done: 'done',
  failed: 'failed',
  cancelled: 'stopped',
};

const LIVE = new Set<AgentTask['status']>(['queued', 'running', 'waiting_approval']);

const DECISION_LABEL: Record<string, string> = {
  allow: 'allowed',
  ask: 'asked you',
  deny: 'refused',
  unknown: 'no such tool',
  invalid: 'bad arguments',
};

export function EngineNotice() {
  const engine = useEngine();
  if (!engine.data || engine.data.available) return null;
  return (
    <p
      role="status"
      className="rounded-md border border-amber/40 bg-amber/10 p-2.5 text-xs leading-relaxed text-ink-2"
      data-testid="engine-unavailable"
    >
      Agents chat without tools for now: {engine.data.reason ?? 'the policy engine is not installed.'} See{' '}
      <span className="font-mono">docs/proposals/phase-3-protected-core.md</span>.
    </p>
  );
}

function RunForm() {
  const api = useApi();
  const agents = useUniverse((s) => s.agents);
  const agentId = useUniverse((s) => s.runAgentId);
  const openAgent = useUniverse((s) => s.openAgent);
  const selectTask = useUniverse((s) => s.selectTask);
  const engine = useEngine();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const ready = !!engine.data?.available && !engine.data.killswitch_engaged;
  const run = () => {
    const instruction = text.trim();
    if (!instruction || !ready) return;
    setBusy(true);
    attempt(
      'Run agent',
      api
        .runAgent(agentId, instruction)
        .then((r) => {
          setText('');
          selectTask(r.task_id);
        })
        .finally(() => setBusy(false)),
    );
  };
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <select
          value={agentId}
          onChange={(e) => openAgent(e.target.value)}
          aria-label="Agent"
          className={`${inputClass} w-32`}
        >
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <Button tone="primary" disabled={!ready || busy || !text.trim()} onClick={run} testid="run-agent">
          <Play className="size-3.5" aria-hidden /> Run
        </Button>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run();
        }}
        rows={3}
        placeholder="Find my notes about…, summarize them, and link them to…"
        aria-label="Instruction"
        className={`${inputClass} w-full resize-none py-1.5 leading-relaxed`}
        data-testid="agent-instruction"
      />
    </div>
  );
}

function TaskRow({ task }: { task: AgentTask }) {
  const agents = useUniverse((s) => s.agents);
  const selectTask = useUniverse((s) => s.selectTask);
  const name = agents.find((a) => a.id === task.agent_id)?.name ?? task.agent_id;
  return (
    <li>
      <button
        type="button"
        onClick={() => selectTask(task.id)}
        className="flex w-full items-start gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-space-3/60"
        data-testid="task-row"
      >
        <span className="pt-1.5">
          <Dot color={STATUS_COLOR[task.status]} pulse={LIVE.has(task.status)} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-ink-1">{task.title}</span>
          <span className="block text-xs text-ink-3">
            {name} · {STATUS_LABEL[task.status]} · {timeAgo(task.created_at)}
          </span>
        </span>
      </button>
    </li>
  );
}

function stepText(step: TaskStep): string {
  if (step.kind === 'llm_call') return `Model call${step.model ? ` · ${step.model}` : ''}`;
  if (step.kind === 'tool_call')
    return `${step.tool ?? '?'} · ${DECISION_LABEL[step.decision ?? ''] ?? step.decision}`;
  if (step.kind === 'tool_result') return `${step.tool ?? '?'} returned`;
  if (step.kind === 'delegate') {
    const agent = /"agent":\s*"([^"]+)"/.exec(step.args)?.[1];
    return agent ? `Delegated to ${agent}` : 'Delegated to a specialist';
  }
  if (step.kind === 'review') return 'Critic reviewed the answer';
  return step.kind;
}

/** A step's stored detail, shortened: the tool arguments, or the result text. */
function stepDetail(step: TaskStep): string {
  const raw = step.kind === 'tool_call' ? step.args : (step.result ?? '');
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') {
      const o = parsed as Record<string, unknown>;
      const text = typeof o.text === 'string' ? o.text : typeof o.content === 'string' ? o.content : null;
      if (text !== null) return text;
      if (typeof o.verdict === 'string') return o.verdict;
    }
  } catch {
    // Not JSON (a model's malformed arguments): show it as is.
  }
  return raw === '{}' ? '' : raw;
}

function Step({ step }: { step: TaskStep }) {
  const [open, setOpen] = useState(false);
  const detail = stepDetail(step);
  const refused = step.decision === 'deny' || step.decision === 'unknown' || step.decision === 'invalid';
  return (
    <li className="text-xs">
      <button
        type="button"
        disabled={!detail}
        onClick={() => setOpen(!open)}
        className="flex w-full items-baseline gap-2 py-0.5 text-left disabled:cursor-default"
      >
        <span className="w-5 shrink-0 text-right font-mono text-ink-3">{step.n}</span>
        <span className={`flex-1 truncate ${refused ? 'text-danger' : 'text-ink-2'}`}>{stepText(step)}</span>
        {step.duration_ms > 0 && <span className="font-mono text-ink-3">{step.duration_ms} ms</span>}
      </button>
      {open && detail && (
        <pre className="mt-1 mb-2 ml-7 max-h-40 overflow-auto rounded-sm bg-space-2 p-2 font-mono text-[11px] whitespace-pre-wrap text-ink-2">
          {detail.slice(0, 4000)}
        </pre>
      )}
    </li>
  );
}

function TaskTrace({ id }: { id: string }) {
  const api = useApi();
  const detail = useTask(id);
  const agents = useUniverse((s) => s.agents);
  const selectTask = useUniverse((s) => s.selectTask);
  const data = detail.data;
  if (!data) return <p className="text-xs text-ink-3">Loading…</p>;
  const { task, steps, children } = data;
  const name = (agentId: string) => agents.find((a) => a.id === agentId)?.name ?? agentId;
  return (
    <div className="space-y-3" data-testid="task-trace">
      <button
        type="button"
        onClick={() => selectTask(task.parent_id)}
        className="flex items-center gap-1 text-xs text-ink-3 hover:text-accent"
      >
        <ChevronLeft className="size-3.5" aria-hidden /> {task.parent_id ? 'Parent task' : 'All tasks'}
      </button>
      <div className="space-y-1">
        <p className="text-sm text-ink-1">{task.title}</p>
        <p className="flex flex-wrap items-center gap-x-2 text-xs text-ink-3">
          <Dot color={STATUS_COLOR[task.status]} pulse={LIVE.has(task.status)} />
          <span data-testid="task-status">{STATUS_LABEL[task.status]}</span>
          <span>· {name(task.agent_id)}</span>
          {task.model && <span>· {task.model}</span>}
          <span>
            · {task.steps_used} steps · {task.tokens_in + task.tokens_out} tokens
          </span>
          {task.tainted && (
            <span title="This task read your files or other outside text, so anything with side effects asked you first">
              · read untrusted content
            </span>
          )}
        </p>
      </div>
      {LIVE.has(task.status) && (
        <Button tone="danger" onClick={() => attempt('Stop task', api.cancelTask(task.id))}>
          <Square className="size-3" aria-hidden /> Stop
        </Button>
      )}
      {task.error && <p className="text-xs text-danger">{task.error}</p>}
      {task.output && (
        <p
          className="max-h-60 overflow-y-auto rounded-md bg-space-2 p-2.5 text-xs leading-relaxed whitespace-pre-wrap text-ink-1 select-text"
          data-testid="task-output"
        >
          {task.output}
        </p>
      )}
      {children.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-ink-3">Specialists</p>
          <ul className="space-y-0.5">
            {children.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => selectTask(c.id)}
                  className="flex w-full items-center gap-2 rounded-sm px-1 py-0.5 text-left text-xs text-ink-2 hover:bg-space-3/60"
                >
                  <Dot color={STATUS_COLOR[c.status]} />
                  {name(c.agent_id)} · {STATUS_LABEL[c.status]}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <p className="mb-1 text-xs text-ink-3">Trace</p>
        <ol className="space-y-0.5" data-testid="task-steps">
          {steps.map((s) => (
            <Step key={s.id} step={s} />
          ))}
        </ol>
      </div>
    </div>
  );
}

function Tasks() {
  const tasks = useTasks();
  const selected = useUniverse((s) => s.selectedTaskId);
  if (selected) return <TaskTrace id={selected} />;
  return (
    <>
      <Section title="Run">
        <RunForm />
      </Section>
      <Section title="Tasks" testid="tasks">
        {tasks.data && tasks.data.length === 0 && (
          <p className="text-xs text-ink-3">No tasks yet. Run one above, or ask Core in chat.</p>
        )}
        <ul className="space-y-0.5">
          {tasks.data?.map((t) => (
            <TaskRow key={t.id} task={t} />
          ))}
        </ul>
      </Section>
    </>
  );
}

const SCOPE_LABEL = (scope: string) =>
  scope === 'self'
    ? 'about you'
    : scope === 'shared'
      ? 'everyone'
      : `${scope.replace(/^agent:/, '')}'s notes`;

function MemoryRow({ memory }: { memory: Memory }) {
  const api = useApi();
  const client = useQueryClient();
  const [editing, setEditing] = useState<string | null>(null);
  const reload = () => client.invalidateQueries({ queryKey: ['memories'] });
  return (
    <li className="space-y-1 rounded-md border border-hairline-1 p-2 text-xs" data-testid="memory">
      {editing === null ? (
        <p className="leading-relaxed text-ink-1 select-text">{memory.content}</p>
      ) : (
        <textarea
          value={editing}
          onChange={(e) => setEditing(e.target.value)}
          rows={3}
          aria-label="Memory"
          className={`${inputClass} w-full resize-none`}
        />
      )}
      <div className="flex items-center gap-2 text-ink-3">
        <span className="flex-1">
          {SCOPE_LABEL(memory.scope)} · {memory.created_by.replace(/^agent:/, '')} ·{' '}
          {timeAgo(memory.created_at)}
        </span>
        {memory.status === 'proposed' ? (
          <>
            <Button
              tone="primary"
              onClick={() => attempt('Approve memory', api.decideMemory(memory.id, true).then(reload))}
            >
              Keep
            </Button>
            <Button
              onClick={() => attempt('Decline memory', api.decideMemory(memory.id, false).then(reload))}
            >
              Discard
            </Button>
          </>
        ) : editing === null ? (
          <>
            <button type="button" title="Edit" onClick={() => setEditing(memory.content)}>
              <Pencil className="size-3.5 hover:text-ink-1" aria-label="Edit" />
            </button>
            <button
              type="button"
              title="Forget"
              onClick={() => attempt('Forget memory', api.deleteMemory(memory.id).then(reload))}
            >
              <Trash2 className="size-3.5 hover:text-danger" aria-label="Forget" />
            </button>
          </>
        ) : (
          <>
            <Button
              tone="primary"
              disabled={!editing.trim()}
              onClick={() =>
                attempt(
                  'Edit memory',
                  api
                    .editMemory(memory.id, editing.trim())
                    .then(reload)
                    .then(() => setEditing(null)),
                )
              }
            >
              Save
            </Button>
            <Button onClick={() => setEditing(null)}>Cancel</Button>
          </>
        )}
      </div>
    </li>
  );
}

function Memories() {
  const api = useApi();
  const client = useQueryClient();
  const proposed = useMemories('proposed');
  const active = useMemories('active');
  const [text, setText] = useState('');
  const add = () => {
    const content = text.trim();
    if (!content) return;
    attempt(
      'Add memory',
      api.createMemory(content).then(() => {
        setText('');
        return client.invalidateQueries({ queryKey: ['memories'] });
      }),
    );
  };
  return (
    <>
      {proposed.data && proposed.data.length > 0 && (
        <Section title="Proposed by agents" testid="memories-proposed">
          <p className="text-xs leading-relaxed text-ink-3">
            Agents only remember things about you once you keep them.
          </p>
          <ul className="space-y-2">
            {proposed.data.map((m) => (
              <MemoryRow key={m.id} memory={m} />
            ))}
          </ul>
        </Section>
      )}
      <Section title="Remembered" testid="memories-active">
        <div className="flex gap-2">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add()}
            placeholder="Something agents should know about you"
            aria-label="New memory"
            className={`${inputClass} flex-1`}
          />
          <Button onClick={add} disabled={!text.trim()}>
            Add
          </Button>
        </div>
        {active.data && active.data.length === 0 && <p className="text-xs text-ink-3">Nothing yet.</p>}
        <ul className="space-y-2">
          {active.data?.map((m) => (
            <MemoryRow key={m.id} memory={m} />
          ))}
        </ul>
      </Section>
    </>
  );
}

export function AgentsPanel() {
  const [view, setView] = useState<'tasks' | 'memory' | 'roster'>('tasks');
  const proposed = useMemories('proposed');
  const waiting = proposed.data?.length ?? 0;
  return (
    <div className="space-y-4" data-testid="agents-panel">
      <EngineNotice />
      <div className="flex gap-1 rounded-md bg-space-2 p-0.5 text-xs">
        {(['tasks', 'memory', 'roster'] as const).map((v) => (
          <button
            key={v}
            type="button"
            aria-pressed={view === v}
            onClick={() => setView(v)}
            className={`flex-1 rounded-sm px-2 py-1 capitalize ${view === v ? 'bg-space-3 text-ink-1' : 'text-ink-3'}`}
            data-testid={`agents-view-${v}`}
          >
            {v}
            {v === 'memory' && waiting > 0 && ` (${waiting})`}
          </button>
        ))}
      </div>
      {view === 'tasks' ? <Tasks /> : view === 'memory' ? <Memories /> : <AgentRoster />}
    </div>
  );
}
