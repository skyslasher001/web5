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

export function Section({
  title,
  children,
  testid,
}: {
  title: string;
  children: ReactNode;
  testid?: string;
}) {
  return (
    <section className="space-y-2 border-b border-hairline-1 pb-4 last:border-0" data-testid={testid}>
      <SectionTitle>{title}</SectionTitle>
      {children}
    </section>
  );
}

export function Button({
  onClick,
  children,
  disabled = false,
  tone = 'plain',
  title,
  testid,
}: {
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
  tone?: 'plain' | 'primary' | 'danger';
  title?: string;
  testid?: string;
}) {
  const toneClass = {
    plain: 'border-hairline-2 text-ink-2 hover:border-accent/60 hover:text-ink-1',
    primary: 'border-accent/60 bg-accent/15 text-ink-1 hover:bg-accent/25',
    danger: 'border-danger/60 text-danger hover:bg-danger/15',
  }[tone];
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      title={title}
      data-testid={testid}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition-colors duration-150 disabled:opacity-40 ${toneClass}`}
    >
      {children}
    </button>
  );
}

/** Text field styling shared by the panels. */
export const inputClass =
  'min-w-0 rounded-md border border-hairline-2 bg-space-2 px-2 py-1 text-xs text-ink-1 placeholder:text-ink-3 focus:border-accent/60 focus:outline-none';
