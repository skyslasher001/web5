// PROTECTED CORE. Safe-mode page logic: plain browser JS, talks only to the preload bridge.
(() => {
  const api = window.universe;
  const $ = (id) => document.getElementById(id);
  const reasons = {
    'core-failed': 'Core failed to start twice, then failed again in safe mode.',
    'renderer-crashed': 'The interface crashed twice within a minute.',
    'ui-failed-to-load': 'The interface files could not be loaded (was `pnpm build` run?).',
  };
  const query = new URLSearchParams(location.search);
  $('reason').textContent = reasons[query.get('reason')] || 'Unknown problem.';

  function render(state) {
    const sup = state && state.supervisor;
    if (!sup) {
      $('core-state').textContent = `Supervisor: ${state ? state.process : 'unknown'}`;
      return;
    }
    const core = sup.services.core;
    // First line only (the why); the full log tail is in the section below.
    const why = core.last_error ? core.last_error.split('\n')[0] : '';
    $('core-state').textContent = `${core.state}${why ? ` · ${why}` : ''}`;
    if (sup.safe_mode.reason) $('reason').textContent += `\n${sup.safe_mode.reason}`;
    const lkg = sup.safe_mode.lkg_commit;
    $('running-from').textContent =
      sup.safe_mode.running_from === 'lkg'
        ? `Last-known-good commit ${lkg ? lkg.slice(0, 10) : ''}`
        : 'Current code';
    $('back').disabled = core.state !== 'healthy';
  }

  async function refreshLogs() {
    try {
      const [core, supervisor] = await Promise.all([api.getLogs('core', 40), api.getLogs('supervisor', 15)]);
      $('log').textContent = `--- core\n${core || '(empty)'}\n\n--- supervisor\n${supervisor || '(empty)'}`;
    } catch (err) {
      $('log').textContent = `Could not read logs: ${err}`;
    }
  }

  async function busy(button, action) {
    button.disabled = true;
    try {
      await action();
    } finally {
      button.disabled = false;
      refreshLogs();
    }
  }

  if (!api) {
    $('summary').textContent = 'The desktop bridge is unavailable; restart the app.';
    return;
  }
  api.getDesktopState().then(render);
  api.onDesktopState(render);
  refreshLogs();
  $('retry').addEventListener('click', (e) => busy(e.currentTarget, () => api.exitSafeMode()));
  $('restart').addEventListener('click', (e) => busy(e.currentTarget, () => api.restartService('core')));
  $('back').addEventListener('click', () => api.reload());
  $('open-logs').addEventListener('click', () => api.openLogsFolder());
})();
