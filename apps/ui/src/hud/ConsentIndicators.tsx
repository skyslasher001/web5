// Always-on-top capture indicators (SPEC §3.4). Nothing can capture in Phase 1, so this renders
// nothing; it exists at the top z-layer so later phases can't forget where indicators go.
export function ConsentIndicators() {
  return (
    <div
      className="pointer-events-none fixed top-14 right-4"
      style={{ zIndex: 'var(--z-consent)' }}
      aria-live="polite"
    />
  );
}
