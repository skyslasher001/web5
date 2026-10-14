// What agents may do, what they spent, what they did: the kill switch, budget, permission rules, MCP servers
// and the audit log. Rules, budget and the kill switch come from the protected policy engine.
import type { MCPServerInfo, PermissionRule } from '@universe/shared-types';
import { tokens } from '@universe/design-tokens';
import { useQueryClient } from '@tanstack/react-query';
import { OctagonX, Plus, RotateCw, ShieldCheck, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { formatUsd, timeAgo } from '../lib/format';
import { useAudit, useBudget, useEngine, useMcpServers, usePermissionRules } from '../lib/queries';
import { useUniverse } from '../state/store';
import { useKillSwitch } from '../lib/killSwitch';
import { EngineNotice } from './AgentsPanel';
import { Button, Dot, inputClass, Section } from './ui';

function KillSwitchSection() {
  const { available, engaged, engage, release } = useKillSwitch();
  return (
    <Section title="Kill switch">
      <p className="text-xs leading-relaxed text-ink-3">
        Stops every agent at once, refuses pending approvals and closes outbound network. Hotkey{' '}
        <span className="font-mono">Ctrl+Alt+Shift+K</span>. Releasing it asks you to confirm in a system
        dialog.
      </p>
      {!available ? (
        <p className="text-xs text-ink-3">Arrives with the Phase 3 protected-core patch.</p>
      ) : engaged ? (
        <Button onClick={release}>Release…</Button>
      ) : (
        <Button tone="danger" onClick={engage} testid="killswitch-engage">
          <OctagonX className="size-3.5" aria-hidden /> Stop all agents
        </Button>
      )}
    </Section>
  );
}

function Budget({ enabled }: { enabled: boolean }) {
  const api = useApi();
  const client = useQueryClient();
  const budget = useBudget(enabled);
  const [cap, setCap] = useState('');
  const data = budget.data;
  if (!data) return null;
  const save = () => {
    const value = Number(cap);
    if (!Number.isFinite(value) || value < 0) return;
    attempt(
      'Set budget cap',
      api.setBudgetCap(value).then((status) => {
        client.setQueryData(['budget'], status);
        setCap('');
      }),
    );
  };
  return (
    <Section title="Budget" testid="budget">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-ink-3">This month</span>
        <span className="font-mono text-xs text-ink-1">
          {formatUsd(data.spent_usd)} of {formatUsd(data.monthly_cap_usd)}
        </span>
      </div>
      <p className="text-xs text-ink-3">
        {data.calls} model calls · {(data.tokens_in + data.tokens_out).toLocaleString()} tokens. Local models
        are free and always allowed; a paid model can only run within the cap.
      </p>
      {data.by_agent.length > 0 && (
        <ul className="space-y-0.5 text-xs">
          {data.by_agent.map((row) => (
            <li key={row.key} className="flex justify-between text-ink-2">
              <span>{row.key}</span>
              <span className="font-mono text-ink-3">
                {row.calls} calls · {formatUsd(row.cost_usd)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <input
          value={cap}
          onChange={(e) => setCap(e.target.value)}
          inputMode="decimal"
          placeholder={`Monthly cap (now ${formatUsd(data.monthly_cap_usd)})`}
          aria-label="Monthly cap in dollars"
          className={`${inputClass} flex-1`}
        />
        <Button onClick={save} disabled={!cap.trim()}>
          Set cap
        </Button>
      </div>
    </Section>
  );
}

const DECISION_COLOR: Record<PermissionRule['decision'], string> = {
  allow: tokens.color.green,
  ask: tokens.color.amber,
  deny: tokens.color.danger,
};

function Rules({ enabled }: { enabled: boolean }) {
  const api = useApi();
  const client = useQueryClient();
  const rules = usePermissionRules(enabled);
  const agents = useUniverse((s) => s.agents);
  const engine = useEngine();
  const [agent, setAgent] = useState('*');
  const [tool, setTool] = useState('');
  const [decision, setDecision] = useState<PermissionRule['decision']>('allow');
  const [tainted, setTainted] = useState(false);
  if (!rules.data) return null;
  const reload = () => client.invalidateQueries({ queryKey: ['rules'] });
  const add = () => {
    if (!tool.trim()) return;
    attempt(
      'Add rule',
      api
        .addPermissionRule({ agent_id: agent, tool: tool.trim(), decision, applies_when_tainted: tainted })
        .then(() => {
          setTool('');
          setTainted(false);
          return reload();
        }),
    );
  };
  return (
    <Section title="Permission rules" testid="rules">
      <p className="text-xs leading-relaxed text-ink-3">
        Without a rule: reading is allowed, writing asks when the agent's definition says so, system actions
        and MCP tools always ask. After an agent reads your files, anything with side effects asks again
        unless the rule says otherwise.
      </p>
      {rules.data.length === 0 && <p className="text-xs text-ink-3">No rules: the defaults above apply.</p>}
      <ul className="space-y-1">
        {rules.data.map((r) => (
          <li key={r.id} className="flex items-center gap-2 text-xs">
            <Dot color={DECISION_COLOR[r.decision]} />
            <span className="flex-1 truncate text-ink-2">
              <span className="text-ink-1">{r.decision}</span> {r.agent_id === '*' ? 'any agent' : r.agent_id}{' '}
              · <span className="font-mono">{r.tool}</span>
              {r.applies_when_tainted && ' · even after reading files'}
            </span>
            <button
              type="button"
              title="Remove rule"
              onClick={() => attempt('Remove rule', api.removePermissionRule(r.id).then(reload))}
            >
              <Trash2 className="size-3.5 text-ink-3 hover:text-danger" aria-label="Remove rule" />
            </button>
          </li>
        ))}
      </ul>
      <div className="grid grid-cols-[auto_1fr] gap-2">
        <select
          value={agent}
          onChange={(e) => setAgent(e.target.value)}
          aria-label="Agent"
          className={inputClass}
        >
          <option value="*">Any agent</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <input
          value={tool}
          onChange={(e) => setTool(e.target.value)}
          list="universe-tools"
          placeholder="Tool, e.g. note.create or mcp.github.*"
          aria-label="Tool"
          className={inputClass}
        />
        <datalist id="universe-tools">
          {engine.data?.tools.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
        <select
          value={decision}
          onChange={(e) => setDecision(e.target.value as PermissionRule['decision'])}
          aria-label="Decision"
          className={inputClass}
        >
          <option value="allow">Allow</option>
          <option value="ask">Ask me</option>
          <option value="deny">Never</option>
        </select>
        <label className="flex items-center gap-1.5 text-xs text-ink-3">
          <input type="checkbox" checked={tainted} onChange={(e) => setTainted(e.target.checked)} />
          even after reading files
        </label>
      </div>
      <Button onClick={add} disabled={!tool.trim()}>
        <Plus className="size-3.5" aria-hidden /> Add rule
      </Button>
    </Section>
  );
}

function McpServer({ server, reload }: { server: MCPServerInfo; reload: () => void }) {
  const api = useApi();
  return (
    <li className="space-y-1 text-xs" data-testid="mcp-server">
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={server.enabled}
          aria-label={`Enable ${server.name}`}
          onChange={(e) =>
            attempt('Update MCP server', api.setMcpServerEnabled(server.id, e.target.checked).then(reload))
          }
        />
        <Dot
          color={
            server.running ? tokens.color.green : server.error ? tokens.color.danger : tokens.color.slate
          }
        />
        <span className="flex-1 truncate text-ink-1" title={[server.command, ...server.args].join(' ')}>
          {server.name}
          <span className="ml-2 text-ink-3">
            {server.running ? `${server.tools.length} tools` : server.enabled ? 'stopped' : 'off'}
          </span>
        </span>
        <button
          type="button"
          title="Restart"
          onClick={() => attempt('Restart MCP server', api.restartMcpServer(server.id).then(reload))}
        >
          <RotateCw className="size-3.5 text-ink-3 hover:text-ink-1" aria-label="Restart" />
        </button>
        <button
          type="button"
          title="Remove"
          onClick={() => attempt('Remove MCP server', api.removeMcpServer(server.id).then(reload))}
        >
          <Trash2 className="size-3.5 text-ink-3 hover:text-danger" aria-label="Remove" />
        </button>
      </div>
      {server.error && <p className="text-danger">{server.error}</p>}
    </li>
  );
}

function McpServers() {
  const api = useApi();
  const client = useQueryClient();
  const servers = useMcpServers(true);
  const [name, setName] = useState('');
  const [command, setCommand] = useState('');
  const reload = () => void client.invalidateQueries({ queryKey: ['mcp'] });
  const add = () => {
    // A plain split: quote-free commands like "npx -y @modelcontextprotocol/server-everything".
    const [cmd, ...args] = command.trim().split(/\s+/);
    if (!name.trim() || !cmd) return;
    attempt(
      'Add MCP server',
      api.addMcpServer({ name: name.trim(), command: cmd, args, env: {} }).then(() => {
        setName('');
        setCommand('');
        reload();
      }),
    );
  };
  return (
    <Section title="MCP servers" testid="mcp">
      <p className="text-xs leading-relaxed text-ink-3">
        Local tool servers (Model Context Protocol) that Core can use. Their tools ask you before every call
        until you set a rule, and what they return is treated as untrusted.
      </p>
      <ul className="space-y-2">
        {servers.data?.map((s) => (
          <McpServer key={s.id} server={s} reload={reload} />
        ))}
      </ul>
      <div className="grid grid-cols-[6rem_1fr] gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value.toLowerCase())}
          placeholder="name"
          aria-label="Server name"
          className={inputClass}
        />
        <input
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          placeholder="Command, e.g. uvx mcp-server-time"
          aria-label="Server command"
          className={`${inputClass} font-mono`}
        />
      </div>
      <Button onClick={add} disabled={!name.trim() || !command.trim()}>
        <Plus className="size-3.5" aria-hidden /> Add server
      </Button>
    </Section>
  );
}

function Audit() {
  const api = useApi();
  const audit = useAudit(true);
  const [verdict, setVerdict] = useState<string | null>(null);
  const verify = () =>
    attempt(
      'Verify audit log',
      api
        .verifyAudit()
        .then((v) =>
          setVerdict(
            v.ok
              ? `Intact: ${v.count} entries, the hash chain checks out.`
              : `Broken at entry ${v.first_bad_seq}: the log was changed outside UNIVERSE.`,
          ),
        ),
    );
  return (
    <Section title="Audit log" testid="audit">
      <div className="flex items-center gap-2">
        <Button onClick={verify}>
          <ShieldCheck className="size-3.5" aria-hidden /> Verify
        </Button>
        {verdict && (
          <span className={`text-xs ${verdict.startsWith('Intact') ? 'text-green' : 'text-danger'}`}>
            {verdict}
          </span>
        )}
      </div>
      <p className="text-xs text-ink-3">
        Ids and hashes only: the log never holds the content of your notes.
      </p>
      <ol className="space-y-0.5 font-mono text-[11px]">
        {audit.data?.map((e) => (
          <li key={e.seq} className="flex gap-2" title={JSON.stringify(e.details)}>
            <span className="w-14 shrink-0 text-ink-3">{timeAgo(e.ts)}</span>
            <span className={`flex-1 truncate ${e.outcome === 'ok' ? 'text-ink-2' : 'text-amber'}`}>
              {e.actor} · {e.action}
              {typeof e.details.tool === 'string' ? ` · ${e.details.tool}` : ''}
              {e.outcome !== 'ok' ? ` · ${e.outcome}` : ''}
            </span>
          </li>
        ))}
      </ol>
    </Section>
  );
}

export function SafetyPanel() {
  const engine = useEngine();
  const policy = !!engine.data?.available;
  return (
    <div className="space-y-4" data-testid="safety-panel">
      <EngineNotice />
      <KillSwitchSection />
      <Budget enabled={policy} />
      <Rules enabled={policy} />
      <McpServers />
      <Audit />
    </div>
  );
}
