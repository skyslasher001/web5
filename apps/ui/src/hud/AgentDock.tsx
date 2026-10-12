import { tokens } from '@universe/design-tokens';
import { hueHex } from '../lib/colors';
import { useUniverse } from '../state/store';
import { Dot, SectionTitle } from './ui';

const LABEL = {
  idle: 'Idle',
  thinking: 'Thinking…',
  replying: 'Replying…',
  error: 'Last reply failed',
} as const;

export function AgentDock() {
  const agents = useUniverse((s) => s.agents);
  const activity = useUniverse((s) => s.agentActivity);
  const safeMode = useUniverse((s) => s.desktop?.supervisor?.safe_mode.active ?? false);
  const setChatOpen = useUniverse((s) => s.setChatOpen);
  return (
    <nav aria-label="Agents" className="glass pointer-events-auto absolute top-16 left-4 w-60 p-4">
      <SectionTitle>Agents</SectionTitle>
      <ul className="space-y-1">
        {agents.map((agent) => {
          const state = safeMode ? 'disabled' : (activity[agent.id] ?? 'idle');
          const busy = state === 'thinking' || state === 'replying';
          const color = state === 'error' ? tokens.color.danger : hueHex(agent.color);
          return (
            <li key={agent.id}>
              <button
                type="button"
                onClick={() => setChatOpen(true)}
                className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left transition-colors duration-150 hover:bg-space-3/60"
                data-testid={`agent-${agent.id}`}
              >
                <Dot color={state === 'disabled' ? tokens.color.slate : color} pulse={busy} />
                <span className="flex-1">
                  <span className="block text-sm font-medium text-ink-1">{agent.name}</span>
                  <span className="block text-xs text-ink-3">
                    {state === 'disabled' ? 'Disabled (safe mode)' : LABEL[state]}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 border-t border-hairline-1 pt-3 text-xs leading-relaxed text-ink-3">
        13 specialists join Core with the agent engine (Phase 3).
      </p>
    </nav>
  );
}
