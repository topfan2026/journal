import type { ReactNode } from 'react';

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[] }) {
  return (
    <div className="flex h-8 shrink-0 items-end gap-0.5 border-b border-ink-800 bg-ink-950 px-1">
      {items.map((it) => (
        <button
          key={it.id}
          onClick={() => onChange(it.id)}
          className={`flex h-7 items-center gap-1.5 rounded-t px-3 text-xs ${value === it.id ? 'bg-ink-900 text-ink-100 shadow-[inset_0_2px_0_#3b82f6]' : 'text-ink-400 hover:text-ink-100'}`}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-2xs uppercase tracking-wide text-ink-500">
      {label}
      {children}
    </label>
  );
}

export const inputCls = 'h-7 rounded border border-ink-700 bg-ink-950 px-2 font-mono text-xs text-ink-100 outline-none focus:border-accent';
export const btnCls = 'inline-flex h-7 items-center justify-center gap-1.5 rounded px-3 text-xs font-medium transition-colors disabled:opacity-40';

export function Stat({ label, value, className = '' }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div className="rounded border border-ink-800 bg-ink-950 px-2 py-1.5">
      <div className="text-2xs uppercase tracking-wide text-ink-500">{label}</div>
      <div className={`font-mono text-sm ${className}`}>{value}</div>
    </div>
  );
}

/** Thin title bar used by every window in a page. */
export function PanelHeader({ children }: { children: ReactNode }) {
  return <div className="flex h-7 shrink-0 items-center gap-1 border-b border-ink-800 bg-ink-950 px-2 text-xs">{children}</div>;
}
