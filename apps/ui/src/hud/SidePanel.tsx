import { useUniverse, type Panel } from '../state/store';
import { AgentsPanel } from './AgentsPanel';
import { ContextPanel } from './ContextPanel';
import { SafetyPanel } from './SafetyPanel';
import { SystemPanel } from './SystemPanel';
import { VaultPanel } from './VaultPanel';

const TABS: { id: Panel; label: string }[] = [
  { id: 'context', label: 'Context' },
  { id: 'vault', label: 'Vault' },
  { id: 'agents', label: 'Agents' },
  { id: 'safety', label: 'Safety' },
  { id: 'system', label: 'System' },
];

export function SidePanel() {
  const panel = useUniverse((s) => s.panel);
  const setPanel = useUniverse((s) => s.setPanel);
  return (
    <aside
      aria-label="Details"
      className="glass pointer-events-auto absolute top-16 right-4 bottom-4 flex w-[22rem] flex-col"
    >
      <div role="tablist" className="flex gap-1 border-b border-hairline-1 p-2">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            type="button"
            aria-selected={panel === tab.id}
            onClick={() => setPanel(tab.id)}
            className={`rounded-md px-2.5 py-1.5 text-sm transition-colors duration-150 ${
              panel === tab.id ? 'bg-space-3 text-ink-1' : 'text-ink-3 hover:text-ink-2'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" key={panel} className="fade-enter flex-1 overflow-y-auto p-4">
        {
          {
            context: <ContextPanel />,
            vault: <VaultPanel />,
            agents: <AgentsPanel />,
            safety: <SafetyPanel />,
            system: <SystemPanel />,
          }[panel]
        }
      </div>
    </aside>
  );
}
