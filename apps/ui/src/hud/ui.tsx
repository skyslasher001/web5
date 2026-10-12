// Small shared HUD primitives.
import { Check, Copy } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { attempt } from '../lib/attempt';

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-sm border border-hairline-2 px-1.5 py-0.5 font-mono text-[11px] leading-none text-ink-2">
      {children}
    </kbd>
  );
}

export function Dot({ color, pulse = false, label }: { color: string; pulse?: boolean; label?: string }) {
  return (
    <span
      className="relative inline-flex size-2 shrink-0"
      role={label ? 'img' : undefined}
      aria-label={label}
    >
      {pulse && <span className="orb-breathe absolute inset-0 rounded-full" style={{ background: color }} />}
      <span
        className="relative size-2 rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
      />
    </span>
  );
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        attempt(
          'Copy',
          navigator.clipboard.writeText(text).then(() => {
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          }),
        );
      }}
      className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs text-ink-2 transition-colors duration-150 hover:text-accent"
      aria-label={`${label}: ${text}`}
    >
      {done ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {done ? 'Copied' : label}
    </button>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-2 font-display text-[11px] font-semibold tracking-[0.14em] text-ink-3 uppercase">
      {children}
    </h3>
  );
}
