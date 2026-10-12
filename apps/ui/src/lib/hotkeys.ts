import { useEffect } from 'react';
import { useUniverse } from '../state/store';

function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
}

export function useHotkeys(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = useUniverse.getState();
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        s.setPaletteOpen(!s.paletteOpen);
        return;
      }
      if (e.key === 'Escape') {
        if (s.paletteOpen) s.setPaletteOpen(false);
        else if (s.zen) s.toggleZen();
        else if (s.chatOpen && !typing(e.target)) s.setChatOpen(false);
        return;
      }
      if (typing(e.target) || e.ctrlKey || e.metaKey || e.altKey || s.paletteOpen) return;
      const key = e.key.toLowerCase();
      if (key === '/') {
        e.preventDefault();
        s.setPaletteOpen(true);
      } else if (key === 'z') s.toggleZen();
      else if (key === 'c') s.setChatOpen(!s.chatOpen);
      else if (key === 's') s.setPanel('system');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
