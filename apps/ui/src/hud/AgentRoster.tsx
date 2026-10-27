// The roster (Agents panel → Agents): every agent with a short synopsis and its stats. Add your own agents,
// turn agents off and on, edit a synopsis, remove the ones you added. Core and Critic always stay on.
import type { AgentCreate, AgentProfile } from '@universe/shared-types';
import { useQueryClient } from '@tanstack/react-query';
import { Pencil, Plus, Trash2, X } from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { hueHex } from '../lib/colors';
import { agentStatsLine } from '../lib/format';
import { useAgentRoster, useEngine } from '../lib/queries';
import { Button, Dot, inputClass, Section } from './ui';

const COLORS = ['cyan', 'violet', 'amber', 'rose', 'green', 'blue', 'slate'] as const;

function useRefresh() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ['roster'] });
}

function AgentCard({ agent }: { agent: AgentProfile }) {
  const api = useApi();
  const refresh = useRefresh();
  const [editing, setEditing] = useState<string | null>(null);
  const state = !agent.enabled ? 'off' : agent.busy ? 'working' : 'idle';
  const save = (text: string) =>
    attempt(
      'Save synopsis',
      api.updateAgent(agent.id, { synopsis: text }).then(() => {
        setEditing(null);
        return refresh();
      }),
    );
  const toggle = () =>
    attempt('Turn agent on or off', api.updateAgent(agent.id, { enabled: !agent.enabled }).then(refresh));
  const remove = () => {
    if (!window.confirm(`Remove ${agent.name}? Its files are kept aside, so it can be restored by hand.`))
      return;
    attempt('Remove agent', api.removeAgent(agent.id).then(refresh));
  };
  return (
    <li
      className={`space-y-1.5 rounded-md border border-hairline-1 p-2.5 text-xs ${agent.enabled ? '' : 'opacity-60'}`}
      data-testid="roster-agent"
      data-agent={agent.id}
    >
      <div className="flex items-center gap-2">
        <Dot color={hueHex(agent.color)} pulse={agent.busy} label={state} />
        <span className="font-display text-sm text-ink-1">{agent.name}</span>
        <span className="rounded-sm bg-space-3 px-1 text-[10px] text-ink-3">
          {agent.origin === 'custom' ? 'yours' : 'built-in'}
        </span>
        <span className="ml-auto text-[11px] text-ink-3" data-testid="roster-state">
          {state}
        </span>
      </div>
      <p className="text-ink-2">{agent.purpose}</p>
      {editing === null ? (
        <div className="group flex items-start gap-1">
          <p className="flex-1 leading-relaxed text-ink-3" data-testid="roster-synopsis">
            {agent.synopsis || 'No synopsis yet.'}
          </p>
          <button
            type="button"
            onClick={() => setEditing(agent.synopsis)}
            aria-label={`Edit ${agent.name}'s synopsis`}
            className="text-ink-3 hover:text-accent"
          >
            <Pencil className="size-3" aria-hidden />
          </button>
        </div>
      ) : (
        <div className="space-y-1">
          <textarea
            value={editing}
            onChange={(e) => setEditing(e.target.value)}
            rows={3}
            maxLength={1200}
            aria-label={`${agent.name}'s synopsis`}
            className={`${inputClass} w-full resize-none leading-relaxed`}
            data-testid="roster-synopsis-editor"
          />
          <div className="flex gap-1">
            <Button tone="primary" onClick={() => save(editing)} testid="roster-synopsis-save">
              Save
            </Button>
            <Button onClick={() => setEditing(null)}>Cancel</Button>
          </div>
        </div>
      )}
      <p className="font-mono text-[11px] text-ink-3" data-testid="roster-stats">
        {agentStatsLine(agent.stats)}
      </p>
      <p className="font-mono text-[10px] text-ink-3">
        {agent.permission_tier} · {agent.model}
        {agent.tools.length > 0 && ` · ${agent.tools.join(', ')}`}
      </p>
      <div className="flex gap-1 pt-0.5">
        <Button
          onClick={toggle}
          disabled={!!agent.locked_reason || (agent.enabled && agent.busy)}
          title={agent.locked_reason ?? (agent.enabled ? 'Turn off: it stops taking tasks' : 'Turn on')}
          testid="roster-toggle"
        >
          {agent.enabled ? 'Turn off' : 'Turn on'}
        </Button>
        {agent.origin === 'custom' && (
          <Button tone="danger" onClick={remove} disabled={agent.busy} testid="roster-remove">
            <Trash2 className="size-3" aria-hidden /> Remove
          </Button>
        )}
      </div>
    </li>
  );
}

const EMPTY: AgentCreate = {
  name: '',
  purpose: '',
  synopsis: '',
  instructions: '',
  color: 'cyan',
  tools: [],
  permission_tier: 'read',
  model: 'local-fast',
  max_steps: 12,
};

function AddAgent({ onDone }: { onDone: () => void }) {
  const api = useApi();
  const refresh = useRefresh();
  const engine = useEngine();
  const [form, setForm] = useState<AgentCreate>(EMPTY);
  const [saving, setSaving] = useState(false);
  const tools = (engine.data?.tools ?? []).filter((t) => t !== 'agent.delegate');
  const set = <K extends keyof AgentCreate>(key: K, value: AgentCreate[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  const ready =
    form.name.trim().length >= 2 && form.purpose.trim().length >= 3 && form.instructions.trim().length >= 10;
  const submit = () => {
    if (!ready || saving) return;
    setSaving(true);
    attempt(
      'Add agent',
      api
        .addAgent(form)
        .then(refresh)
        .then(onDone)
        .finally(() => setSaving(false)),
    );
  };
  const field = 'space-y-0.5 text-[11px] text-ink-3';
  return (
    <div className="space-y-2 rounded-md border border-accent/30 p-2.5" data-testid="add-agent-form">
      <label className={`block ${field}`}>
        Name
        <input
          value={form.name}
          onChange={(e) => set('name', e.target.value)}
          maxLength={40}
          className={`${inputClass} w-full`}
          data-testid="add-agent-name"
        />
      </label>
      <label className={`block ${field}`}>
        What it does (one line)
        <input
          value={form.purpose}
          onChange={(e) => set('purpose', e.target.value)}
          maxLength={200}
          className={`${inputClass} w-full`}
          data-testid="add-agent-purpose"
        />
      </label>
      <label className={`block ${field}`}>
        Synopsis (a few sentences, shown here)
        <textarea
          value={form.synopsis}
          onChange={(e) => set('synopsis', e.target.value)}
          rows={2}
          maxLength={1200}
          className={`${inputClass} w-full resize-none`}
          data-testid="add-agent-synopsis"
        />
      </label>
      <label className={`block ${field}`}>
        Instructions (how it should work; its system prompt)
        <textarea
          value={form.instructions}
          onChange={(e) => set('instructions', e.target.value)}
          rows={4}
          maxLength={8000}
          className={`${inputClass} w-full resize-none`}
          data-testid="add-agent-instructions"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <label className={field}>
          Colour
          <select
            value={form.color}
            onChange={(e) => set('color', e.target.value)}
            className={`${inputClass} block`}
          >
            {COLORS.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label className={field}>
          Access
          <select
            value={form.permission_tier}
            onChange={(e) => set('permission_tier', e.target.value as AgentCreate['permission_tier'])}
            className={`${inputClass} block`}
            data-testid="add-agent-tier"
          >
            <option value="read">read only</option>
            <option value="write">read and write</option>
          </select>
        </label>
        <label className={field}>
          Model
          <select
            value={form.model}
            onChange={(e) => set('model', e.target.value as AgentCreate['model'])}
            className={`${inputClass} block`}
          >
            <option value="local-fast">fast</option>
            <option value="local-large">large</option>
          </select>
        </label>
      </div>
      {tools.length > 0 && (
        <fieldset className={field}>
          <legend>Tools (every call still goes through your permission rules and approvals)</legend>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
            {tools.map((t) => (
              <label key={t} className="flex items-center gap-1 font-mono text-[11px] text-ink-2">
                <input
                  type="checkbox"
                  checked={(form.tools ?? []).includes(t)}
                  onChange={(e) =>
                    set(
                      'tools',
                      e.target.checked
                        ? [...(form.tools ?? []), t]
                        : (form.tools ?? []).filter((x) => x !== t),
                    )
                  }
                />
                {t}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <div className="flex gap-1">
        <Button tone="primary" onClick={submit} disabled={!ready || saving} testid="add-agent-save">
          Add agent
        </Button>
        <Button onClick={onDone}>
          <X className="size-3" aria-hidden /> Cancel
        </Button>
      </div>
    </div>
  );
}

export function AgentRoster() {
  const roster = useAgentRoster();
  const [adding, setAdding] = useState(false);
  const agents = roster.data ?? [];
  const on = agents.filter((a) => a.enabled).length;
  return (
    <Section title={`Agents · ${on} on of ${agents.length}`} testid="agent-roster">
      {adding ? (
        <AddAgent onDone={() => setAdding(false)} />
      ) : (
        <Button onClick={() => setAdding(true)} testid="add-agent">
          <Plus className="size-3.5" aria-hidden /> Add an agent
        </Button>
      )}
      {roster.isError && <p className="text-xs text-danger">Couldn't load the agents.</p>}
      <ul className="space-y-2">
        {agents.map((a) => (
          <AgentCard key={a.id} agent={a} />
        ))}
      </ul>
    </Section>
  );
}
