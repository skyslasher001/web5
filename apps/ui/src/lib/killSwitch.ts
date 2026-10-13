// The kill switch as the renderer sees it: Electron main owns the state (protected core).
import { attempt } from './attempt';
import { bridge } from './bridge';
import { useEngine } from './queries';
import { useUniverse } from '../state/store';

export function useKillSwitch() {
  const desktop = useUniverse((s) => s.killSwitch);
  const engine = useEngine();
  const engaged = desktop.engaged || !!engine.data?.killswitch_engaged;
  return {
    available: desktop.available,
    engaged,
    engage: () =>
      attempt(
        'Kill switch',
        bridge()
          .setKillSwitch(true)
          .then((state) => useUniverse.getState().setKillSwitch(state)),
      ),
    /** Electron shows a native confirmation; the state only changes if you confirm there. */
    release: () =>
      attempt(
        'Release the kill switch',
        bridge()
          .setKillSwitch(false)
          .then((state) => useUniverse.getState().setKillSwitch(state)),
      ),
  };
}
