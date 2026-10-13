import { Command, defaultFilter } from 'cmdk';
import {
  ArchiveRestore,
  Bomb,
  Bot,
  ClipboardPaste,
  FolderOpen,
  FolderPlus,
  Gauge,
  Grid2x2,
  HardDrive,
  List,
  MessageSquare,
  MessageSquarePlus,
  NotebookPen,
  OctagonX,
  Orbit,
  PanelRight,
  RefreshCw,
  RotateCw,
  ScrollText,
  ShieldCheck,
  Search,
  Sparkles,
  Telescope,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useApi } from '../lib/api-context';
import { attempt } from '../lib/attempt';
import { bridge } from '../lib/bridge';
import { useProjects } from '../lib/queries';
import { useUniverse } from '../state/store';
import { useKillSwitch } from '../lib/killSwitch';
import { Kbd } from './ui';

const VAULT_SEARCH = 'universe:vault-search';

/** cmdk's fuzzy filter, except the vault-search row always shows and always ranks last. */
function paletteFilter(value: string, search: string, keywords?: string[]): number {
  return value === VAULT_SEARCH ? 0.0001 : defaultFilter(value, search, keywords);
}

function Item({
  icon,
  label,
  hint,
  shortcut,
  onSelect,
  value,
}: {
  icon: ReactNode;
  label: string;
  hint?: string;
  shortcut?: string;
  onSelect: () => void;
  /** What the filter matches against (default: the label and hint). */
  value?: string;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      value={value ?? `${label} ${hint ?? ''}`}
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
  const api = useApi();
  const projects = useProjects();
  const killSwitch = useKillSwitch();
  const [typed, setTyped] = useState('');
  const close = () => {
    s.setPaletteOpen(false);
    setTyped('');
  };
  const run = (action: () => void) => () => {
    close();
    action();
  };
  const group =
    'px-2 pt-2 text-[11px] font-semibold tracking-[0.14em] text-ink-3 uppercase [&_[cmdk-group-heading]]:px-1 [&_[cmdk-group-heading]]:pb-1';
  return (
    <Command.Dialog
      open={open}
      onOpenChange={(next) => (next ? s.setPaletteOpen(true) : close())}
      label="Command palette"
      filter={paletteFilter}
      overlayClassName="fixed inset-0 bg-space-0/60"
      contentClassName="glass-strong fixed top-24 left-1/2 w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden shadow-2xl"
      style={{ zIndex: 'var(--z-command)' }}
    >
      <Command.Input
        value={typed}
        onValueChange={setTyped}
        placeholder="Type a command…"
        className="w-full border-b border-hairline-1 bg-transparent px-4 py-3.5 text-sm text-ink-1 placeholder:text-ink-3 focus:outline-none"
      />
      <Command.List className="max-h-[22rem] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-6 text-center text-sm text-ink-3">
          No matching command.
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
        <Command.Group heading="Agents" className={group}>
          <Item
            icon={<Bot className="size-4" />}
            label="Agents & tasks"
            hint="run a task, see traces"
            shortcut="A"
            onSelect={run(() => s.setPanel('agents'))}
          />
          {s.agents
            .filter((a) => a.id !== 'core')
            .map((a) => (
              <Item
                key={a.id}
                icon={<Bot className="size-4" />}
                label={`Give ${a.name} a task`}
                hint={a.purpose}
                onSelect={run(() => s.openAgent(a.id))}
              />
            ))}
          <Item
            icon={<ShieldCheck className="size-4" />}
            label="Safety: rules, budget & MCP servers"
            onSelect={run(() => s.setPanel('safety'))}
          />
          <Item
            icon={<ScrollText className="size-4" />}
            label="Audit log"
            onSelect={run(() => s.setPanel('safety'))}
          />
          {killSwitch.available && !killSwitch.engaged && (
            <Item
              icon={<OctagonX className="size-4" />}
              label="Engage the kill switch"
              hint="stop every agent now"
              shortcut="Ctrl+Alt+Shift+K"
              onSelect={run(killSwitch.engage)}
            />
          )}
          {killSwitch.available && killSwitch.engaged && (
            <Item
              icon={<OctagonX className="size-4" />}
              label="Release the kill switch…"
              onSelect={run(killSwitch.release)}
            />
          )}
        </Command.Group>
        <Command.Group heading="Capture" className={group}>
          <Item
            icon={<NotebookPen className="size-4" />}
            label="Quick capture"
            hint="write a note from anywhere"
            onSelect={run(() => bridge().showCommandBar('capture'))}
          />
          <Item
            icon={<ClipboardPaste className="size-4" />}
            label="Save clipboard to inbox"
            onSelect={run(() =>
              attempt(
                'Save clipboard',
                bridge()
                  .captureClipboard()
                  .then((r) => useUniverse.getState().addNotice(r.ok ? 'good' : 'warn', r.message)),
              ),
            )}
          />
          <Item
            icon={<FolderPlus className="size-4" />}
            label="Add a watched folder"
            hint="copies new files in"
            onSelect={run(() =>
              attempt(
                'Add watched folder',
                bridge()
                  .pickFolder('Watch a folder')
                  .then(async (path) => {
                    if (!path) return;
                    await api.addWatchedFolder({ path, recursive: true });
                    s.addNotice('good', `Watching ${path}`);
                  }),
              ),
            )}
          />
        </Command.Group>
        <Command.Group heading="View" className={group}>
          <Item
            icon={<Orbit className="size-4" />}
            label="Universe view"
            shortcut="U"
            onSelect={run(() => s.setView('universe'))}
          />
          <Item
            icon={<Grid2x2 className="size-4" />}
            label="Grid view"
            shortcut="G"
            onSelect={run(() => s.setView('grid'))}
          />
          <Item
            icon={<List className="size-4" />}
            label="List view"
            shortcut="L"
            onSelect={run(() => s.setView('list'))}
          />
          <Item
            icon={<ArchiveRestore className="size-4" />}
            label="Show the trash"
            onSelect={run(() => {
              s.setShowTrash(true);
              if (s.view === 'universe') s.setView('list');
            })}
          />
          <Item
            icon={<HardDrive className="size-4" />}
            label="Vault, backups & watched folders"
            shortcut="V"
            onSelect={run(() => s.setPanel('vault'))}
          />
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
            icon={<HardDrive className="size-4" />}
            label="Back up now"
            onSelect={run(() =>
              attempt(
                'Backup',
                api.runBackup().then(() => s.addNotice('info', 'Backup started')),
              ),
            )}
          />
          <Item
            icon={<RotateCw className="size-4" />}
            label="Restart Core"
            onSelect={run(() => attempt('Restart Core', bridge().restartService('core')))}
          />
          <Item
            icon={<Bomb className="size-4" />}
            label="Simulate a Core crash"
            hint="the supervisor brings it back"
            onSelect={run(() => attempt('Simulated crash', bridge().killService('core')))}
          />
          <Item
            icon={<FolderOpen className="size-4" />}
            label="Open logs folder"
            onSelect={run(() => attempt('Open logs folder', bridge().openLogsFolder()))}
          />
          <Item
            icon={<RefreshCw className="size-4" />}
            label="Reload interface"
            onSelect={run(() => bridge().reload())}
          />
        </Command.Group>
        {typed.trim() && (
          <Command.Group heading="Vault" className={group}>
            <Item
              icon={<Search className="size-4" />}
              label={`Search the vault for “${typed.trim()}”`}
              value={VAULT_SEARCH}
              onSelect={run(() => {
                s.setShowTrash(false);
                s.setQuery(typed.trim());
              })}
            />
          </Command.Group>
        )}
      </Command.List>
    </Command.Dialog>
  );
}
