import { useEffect, useRef, useState } from 'react';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { UNIVERSE, WATCHLISTS } from '../data/universe';

const typing = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName));

/**
 * Global keyboard behavior: type letters anywhere to enter a symbol, ↑/↓ (or space) to step
 * through the active watchlist, Shift+V to add to favorites, Esc to drop the drawing tool.
 */
export function SymbolEntry() {
  const [text, setText] = useState<string | null>(null);
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const open = () => setText('');
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      const ws = useWorkspace.getState();
      if (e.key === 'V' && e.shiftKey) { e.preventDefault(); ws.toggleFavorite(ws.symbol); return; }
      if (e.key === 'Escape') { ws.set('tool', 'cursor'); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === ' ') {
        const list = ws.watchlist === 'My Favorites' ? ws.customWatchlist : ws.watchlist === 'Flagged' ? Object.keys(ws.flags) : WATCHLISTS[ws.watchlist] ?? WATCHLISTS['High Cap'];
        if (!list.length) return;
        e.preventDefault();
        const i = list.indexOf(ws.symbol);
        const next = list[(i + (e.key === 'ArrowUp' ? -1 : 1) + list.length) % list.length];
        useMarket.getState().ensure(next);
        ws.setSymbol(next);
        return;
      }
      if (/^[a-zA-Z]$/.test(e.key) && !e.shiftKey) { e.preventDefault(); setText(e.key.toUpperCase()); setSel(0); }
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('chartdesk:symbol-entry', open);
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('chartdesk:symbol-entry', open); };
  }, []);
  useEffect(() => { if (text !== null) inputRef.current?.focus(); }, [text !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  if (text === null) return null;
  const q = text.trim().toUpperCase();
  const matches = q
    ? [...UNIVERSE.filter((u) => u.symbol.startsWith(q)), ...UNIVERSE.filter((u) => !u.symbol.startsWith(q) && u.name.toUpperCase().includes(q))].slice(0, 8)
    : UNIVERSE.slice(0, 8);
  const go = (s: string) => {
    if (!s) return;
    useMarket.getState().ensure(s);
    useWorkspace.getState().setSymbol(s);
    setText(null);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 pt-32" onClick={() => setText(null)}>
      <div className="w-80 rounded-lg border border-ink-600 bg-ink-850 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => { setText(e.target.value.toUpperCase()); setSel(0); }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setText(null);
            else if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, matches.length - 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            else if (e.key === 'Enter') go(matches[sel]?.symbol.startsWith(q) || !q ? matches[sel]?.symbol ?? q : q);
          }}
          className="h-11 w-full rounded-t-lg border-b border-ink-700 bg-transparent px-4 text-lg font-semibold uppercase tracking-wide outline-none"
          placeholder="Symbol"
          aria-label="Symbol"
        />
        {matches.map((m, i) => (
          <button key={m.symbol} onMouseEnter={() => setSel(i)} onClick={() => go(m.symbol)} className={`flex w-full items-center gap-3 px-4 py-1.5 text-left text-xs ${i === sel ? 'bg-accent/20' : ''}`}>
            <b className="w-14">{m.symbol}</b><span className="truncate text-ink-400">{m.name}</span>
          </button>
        ))}
        <div className="border-t border-ink-700 px-4 py-1.5 text-[10px] text-ink-500">Enter to open · Esc to cancel · ↑↓ in the app steps through the watchlist</div>
      </div>
    </div>
  );
}
