import { useEffect } from 'react';
import { LAYOUTS, useUniverse } from '../state/store';
import { rig } from '../universe/scene/helpers';
import { NOTCH } from '../universe/scene/zoom';

/** Keys typed into a field (including a dropdown, where letters pick an option) are never shortcuts. */
export function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return (
    !!el &&
    (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
  );
}

export function modalOpen(s: { viewerItemId: string | null; dashboardProjectId: string | null }): boolean {
  return s.viewerItemId !== null || s.dashboardProjectId !== null;
}

export function useHotkeys(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = useUniverse.getState();
      // Ctrl+Alt+Shift+K is the kill switch (a global shortcut in Electron main), never the palette.
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        s.setPaletteOpen(!s.paletteOpen);
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === '.') {
        // Approvals tray (ARCHITECTURE.md §6.5): focus the first waiting approval, or open the Agents panel.
        e.preventDefault();
        const approve = document.querySelector<HTMLButtonElement>('[data-testid="approve"]');
        if (approve) approve.focus();
        else s.setPanel('agents');
        return;
      }
      if (e.key === 'Escape') {
        if (s.paletteOpen) s.setPaletteOpen(false);
        else if (s.zen) s.toggleZen();
        else if (typing(e.target)) return;
        else if (s.chatOpen) s.setChatOpen(false);
        else if (s.view === 'universe' && s.zoomOut()) return;
        else if (s.selectedItemId) s.selectItem(null);
        else if (s.query) s.setQuery('');
        else if (s.view !== 'universe') s.setView('universe');
        return;
      }
      if (typing(e.target) || e.ctrlKey || e.metaKey || e.altKey || s.paletteOpen) return;
      // A viewer or dashboard is modal: single-key shortcuts would act behind it (Z would even close it).
      if (modalOpen(s)) return;
      const key = e.key.toLowerCase();
      if (key === '/') {
        e.preventDefault();
        s.focusSearch();
      } else if (key === 'z') s.toggleZen();
      else if (key === 'c') s.setChatOpen(!s.chatOpen);
      else if (key === 's') s.setPanel('system');
      else if (key === 'v') s.setPanel('vault');
      else if (key === 'a') s.setPanel('agents');
      else if (key === 'g') s.setView('grid');
      else if (key === 'l') s.setView('list');
      else if (key === 'u') s.setView('universe');
      else if (key === 'h') {
        s.setView('universe');
        s.flyHome();
      } else if ((key === '+' || key === '=' || key === '-') && s.view === 'universe') {
        e.preventDefault();
        rig.zoomBy(key === '-' ? NOTCH * NOTCH : 1 / (NOTCH * NOTCH)); // two wheel notches per key press
      } else if (key >= '1' && key <= '4') {
        s.setLayout(LAYOUTS[Number(key) - 1]!);
        s.setView('universe');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
