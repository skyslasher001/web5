import { Command } from 'cmdk';
import {
  Bomb,
  FolderOpen,
  Gauge,
  MessageSquare,
  MessageSquarePlus,
  PanelRight,
  RefreshCw,
  RotateCw,
  Sparkles,
  Telescope,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { bridge } from '../lib/bridge';
import { useProjects } from '../lib/queries';
import { useUniverse } from '../state/store';
import { Kbd } from './ui';

function Item({
  icon,
  label,
  hint,
  shortcut,
  onSelect,
}: {
  icon: ReactNode;
  label: string;
  hint?: string;
  shortcut?: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      value={`${label} ${hint ?? ''}`}
      className="flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm text-ink-2 data-[selected=true]:bg-space-3 data-[selected=true]:text-ink-1"
    >
      <span className="text-ink-3">{icon}</span>
      <span className="flex-1">
        {label}
        {hint && <span className="ml-2 text-xs text-ink-3">{hint}</span>}
      </span>
      {shortcut && <Kbd>{shortcut}</Kbd>}
    </Command.Item>
  );
}

export function CommandPalette() {
  const open = useUniverse((s) => s.paletteOpen);
  const s = useUniverse();
  const projects = useProjects();
  const run = (action: () => void) => () => {
    s.setPaletteOpen(false);
    action();
  };
  const group =
    'px-2 pt-2 text-[11px] font-semibold tracking-[0.14em] text-ink-3 uppercase [&_[cmdk-group-heading]]:px-1 [&_[cmdk-group-heading]]:pb-1';
  return (
    <Command.Dialog
      open={open}
      onOpenChange={s.setPaletteOpen}
      label="Command palette"
      overlayClassName="fixed inset-0 bg-space-0/60"
      contentClassName="glass-strong fixed top-24 left-1/2 w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden shadow-2xl"
      style={{ zIndex: 'var(--z-command)' }}
    >
      <Command.Input
        placeholder="Type a command…"
        className="w-full border-b border-hairline-1 bg-transparent px-4 py-3.5 text-sm text-ink-1 placeholder:text-ink-3 focus:outline-none"
      />
      <Command.List className="max-h-[22rem] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-6 text-center text-sm text-ink-3">
          No matching command. Searching your vault arrives in Phase 2.
        </Command.Empty>
        <Command.Group heading="Chat" className={group}>
          <Item
            icon={<MessageSquare className="size-4" />}
            label="Toggle chat"
            shortcut="C"
            onSelect={run(() => s.setChatOpen(!s.chatOpen))}
          />
          <Item
            icon={<MessageSquarePlus className="size-4" />}
            label="New chat"
            onSelect={run(() => s.newConversation())}
          />
        </Command.Group>
        <Command.Group heading="View" className={group}>
          <Item
            icon={<Sparkles className="size-4" />}
            label="Toggle zen mode"
            shortcut="Z"
            onSelect={run(s.toggleZen)}
          />
          <Item
            icon={<Gauge className="size-4" />}
            label="System & models"
            shortcut="S"
            onSelect={run(() => s.setPanel('system'))}
          />
          <Item
            icon={<PanelRight className="size-4" />}
            label="Context"
            onSelect={run(() => s.setPanel('context'))}
          />
        </Command.Group>
        {projects.data && projects.data.length > 0 && (
          <Command.Group heading="Galaxies" className={group}>
            {projects.data.map((p) => (
              <Item
                key={p.id}
                icon={<Telescope className="size-4" />}
                label={`Go to ${p.name}`}
                onSelect={run(() => s.selectProject(p.id))}
              />
            ))}
          </Command.Group>
        )}
        <Command.Group heading="System" className={group}>
          <Item
            icon={<RotateCw className="size-4" />}
            label="Restart Core"
            onSelect={run(() => void bridge().restartService('core'))}
          />
          <Item
            icon={<Bomb className="size-4" />}
            label="Simulate a Core crash"
            hint="the supervisor brings it back"
            onSelect={run(() => void bridge().killService('core'))}
          />
          <Item
            icon={<FolderOpen className="size-4" />}
            label="Open logs folder"
            onSelect={run(() => void bridge().openLogsFolder())}
          />
          <Item
            icon={<RefreshCw className="size-4" />}
            label="Reload interface"
            onSelect={run(() => bridge().reload())}
          />
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
