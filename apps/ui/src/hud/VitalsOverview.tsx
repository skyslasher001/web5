// System Vitals (SPEC §20, Phase 5): Core's heartbeat at a glance. Service health, loaded models, the job
// queue, recent errors, Forge and backups, each one line with a colour; errors and Forge open the Forge panel.
import { tokens } from '@universe/design-tokens';
import { ChevronRight } from 'lucide-react';
import {
  useBackupStatus,
  useErrors,
  useForgeProposals,
  useForgeStatus,
  useModels,
  useQueueStats,
} from '../lib/queries';
import {
  backupVital,
  errorsVital,
  forgeVital,
  modelsVital,
  queueVital,
  servicesVital,
  type Vital,
  type VitalLevel,
} from '../lib/vitals';
import { useUniverse } from '../state/store';
import { Dot } from './ui';

const LEVEL_COLOR: Record<VitalLevel, string> = {
  good: tokens.color.green,
  busy: tokens.color.accent,
  warn: tokens.color.amber,
  bad: tokens.color.danger,
  off: tokens.color.slate,
};

function VitalRow({ name, vital, onOpen }: { name: string; vital: Vital; onOpen?: () => void }) {
  const body = (
    <>
      <Dot color={LEVEL_COLOR[vital.level]} pulse={vital.level === 'busy'} label={vital.level} />
      <span className="w-16 shrink-0 text-ink-2">{name}</span>
      <span className="min-w-0 flex-1 truncate text-ink-1" title={vital.text}>
        {vital.text}
      </span>
      {onOpen && <ChevronRight className="size-3.5 shrink-0 text-ink-3" aria-hidden />}
    </>
  );
  const cls = 'flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs';
  return (
    <li data-testid={`vital-${name.toLowerCase()}`} data-level={vital.level}>
      {onOpen ? (
        <button type="button" onClick={onOpen} className={`${cls} hover:bg-white/5`}>
          {body}
        </button>
      ) : (
        <div className={cls}>{body}</div>
      )}
    </li>
  );
}

export function VitalsOverview() {
  const services = useUniverse((s) => s.desktop?.supervisor?.services);
  const models = useModels();
  const queue = useQueueStats();
  const errors = useErrors(true);
  const forge = useForgeStatus();
  const proposals = useForgeProposals();
  const backups = useBackupStatus(true);
  const openForge = () => useUniverse.getState().openForge(null);
  return (
    <ul className="space-y-0.5" data-testid="system-vitals">
      <VitalRow name="Services" vital={servicesVital(services)} />
      <VitalRow name="Models" vital={modelsVital(models.data)} />
      <VitalRow name="Queue" vital={queueVital(queue.data)} />
      <VitalRow name="Errors" vital={errorsVital(errors.data)} onOpen={openForge} />
      <VitalRow name="Forge" vital={forgeVital(forge.data, proposals.data)} onOpen={openForge} />
      <VitalRow name="Backups" vital={backupVital(backups.data)} />
    </ul>
  );
}
