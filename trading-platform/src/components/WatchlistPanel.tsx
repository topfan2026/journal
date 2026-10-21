import { useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Flag, Plus, Star, X } from 'lucide-react';
import { useMarket } from '../store/market';
import { useWorkspace, type FlagColor } from '../store/workspace';
import { infoFor, WATCHLISTS } from '../data/universe';
import { sma } from '../lib/indicators';
import { pct, tone } from '../lib/format';
import { PanelHeader } from './ui';

export const FLAG_CLS: Record<FlagColor, string> = { red: 'text-red-500', yellow: 'text-yellow-400', green: 'text-green-500', blue: 'text-blue-400', purple: 'text-purple-400' };

type Col = 'symbol' | 'last' | 'chg' | 'buzz';

/** Volume relative to its 50-bar average, as % above/below (TC2000-style "Vol Buzz"). */
export function volBuzz(volumes: number[]): number | null {
  const avg = sma(volumes, 50);
  const a = avg[avg.length - 2] ?? avg[avg.length - 1];
  return a ? (volumes[volumes.length - 1] / a - 1) * 100 : null;
}

/**
 * The watchlist window. `fixed` pins it to one list (e.g. My Favorites); otherwise the header
 * dropdown chooses among the built-in lists, flagged symbols and favorites.
 */
export function WatchlistPanel({ fixed }: { fixed?: 'favorites' }) {
  const { watchlist, customWatchlist, flags, symbol, setSymbol, set, cycleFlag, toggleFavorite } = useWorkspace();
  const bars = useMarket((s) => s.bars);
  const prev = useMarket((s) => s.prevClose);
  const ensure = useMarket((s) => s.ensure);
  const [sort, setSort] = useState<{ col: Col; dir: 1 | -1 } | null>(null);
  const [filter, setFilter] = useState('');
  const [adding, setAdding] = useState('');

  const lists: Record<string, string[]> = { ...WATCHLISTS, 'My Favorites': customWatchlist, Flagged: Object.keys(flags) };
  const name = fixed === 'favorites' ? 'My Favorites' : watchlist in lists ? watchlist : 'High Cap';
  const symbols = lists[name];

  const rows = useMemo(() => symbols.map((s) => {
    const b = bars[s];
    const lastPx = b?.[b.length - 1]?.close ?? 0;
    return {
      symbol: s, name: infoFor(s).name, last: lastPx,
      chg: prev[s] ? ((lastPx - prev[s]) / prev[s]) * 100 : 0,
      buzz: b ? volBuzz(b.map((x) => x.volume)) : null,
    };
  }), [symbols, bars, prev]);

  const shown = rows
    .filter((r) => !filter || r.symbol.includes(filter.toUpperCase()) || r.name.toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => {
      if (!sort) return 0;
      if (sort.col === 'symbol') return a.symbol.localeCompare(b.symbol) * sort.dir;
      return (((a[sort.col] ?? -Infinity) as number) - ((b[sort.col] ?? -Infinity) as number)) * sort.dir;
    });
  const pos = shown.findIndex((r) => r.symbol === symbol);
  const th = (col: Col, labelText: string, cls = '') => (
    <th onClick={() => setSort((s) => (s?.col === col ? (s.dir === -1 ? { col, dir: 1 } : null) : { col, dir: -1 }))} className={`cursor-pointer select-none px-1.5 py-1 font-medium hover:text-ink-100 ${cls}`}>
      {labelText}{sort?.col === col && (sort.dir === 1 ? <ArrowUp size={9} className="inline" /> : <ArrowDown size={9} className="inline" />)}
    </th>
  );

  return (
    <div className="flex h-full flex-col bg-[#0b0e13] text-xs">
      <PanelHeader>
        {fixed ? (
          <span className="flex items-center gap-1 font-semibold text-ink-100"><Star size={11} className="text-yellow-400" /> My Favorites</span>
        ) : (
          <select className="bg-transparent font-semibold text-ink-100 outline-none" value={name} onChange={(e) => set('watchlist', e.target.value)}>
            {Object.keys(lists).map((n) => <option key={n} className="bg-ink-900">{n}</option>)}
          </select>
        )}
        <input className="ml-2 h-5 w-20 rounded border border-ink-700 bg-ink-950 px-1 text-2xs outline-none focus:border-accent" placeholder="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {fixed && (
          <form className="ml-auto flex" onSubmit={(e) => { e.preventDefault(); const s = adding.trim().toUpperCase(); if (s && !customWatchlist.includes(s)) { ensure(s); set('customWatchlist', [...customWatchlist, s]); } setAdding(''); }}>
            <input className="h-5 w-16 rounded-l border border-ink-700 bg-ink-950 px-1 text-2xs uppercase outline-none" placeholder="Add" value={adding} onChange={(e) => setAdding(e.target.value)} />
            <button className="rounded-r bg-ink-700 px-1 hover:bg-ink-600" aria-label="Add symbol"><Plus size={11} /></button>
          </form>
        )}
      </PanelHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full">
          <thead className="sticky top-0 z-10 bg-ink-950 text-2xs text-ink-500">
            <tr>
              <th className="w-5 px-1 py-1"><Flag size={9} /></th>
              {th('symbol', 'Sym', 'text-left')}
              {th('last', 'Last', 'text-right')}
              {th('chg', '% Chg', 'text-right')}
              {th('buzz', 'Vol Buzz', 'text-right')}
              <th className="w-4" />
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.symbol} onClick={() => { ensure(r.symbol); setSymbol(r.symbol); }}
                className={`group cursor-pointer border-b border-ink-850 ${r.symbol === symbol ? 'bg-accent/20' : 'hover:bg-ink-850'}`}>
                <td className="px-1" onClick={(e) => { e.stopPropagation(); cycleFlag(r.symbol); }} title="Click to flag (cycles colors)">
                  <Flag size={10} className={flags[r.symbol] ? `${FLAG_CLS[flags[r.symbol]]} fill-current` : 'text-ink-700 group-hover:text-ink-500'} />
                </td>
                <td className="px-1.5 py-0.5">
                  <div className="font-semibold text-ink-100">{r.symbol}</div>
                  <div className="max-w-[130px] truncate text-[9px] leading-tight text-ink-500">{r.name}</div>
                </td>
                <td className="px-1.5 text-right font-mono">{r.last.toFixed(2)}</td>
                <td className={`px-1.5 text-right font-mono ${tone(r.chg)}`}>{pct(r.chg)}</td>
                <td className={`px-1.5 text-right font-mono ${r.buzz !== null && r.buzz > 50 ? 'text-up' : r.buzz !== null && r.buzz < -30 ? 'text-down' : 'text-ink-300'}`}>
                  {r.buzz === null ? '—' : `${r.buzz >= 0 ? '+' : ''}${r.buzz.toFixed(1)}%`}
                </td>
                <td className="pr-1">
                  {fixed && <button className="hidden text-ink-500 hover:text-down group-hover:block" onClick={(e) => { e.stopPropagation(); toggleFavorite(r.symbol); }} aria-label="Remove"><X size={10} /></button>}
                </td>
              </tr>
            ))}
            {!shown.length && (
              <tr><td colSpan={6} className="p-4 text-center text-2xs text-ink-500">{fixed ? 'Shift+V adds the current symbol to favorites' : 'No symbols'}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex h-5 shrink-0 items-center border-t border-ink-800 px-2 text-[10px] text-ink-500">
        {pos >= 0 ? `#${pos + 1} of ` : ''}{shown.length} items in watchlist
        <span className="ml-auto">↑↓ to step through</span>
      </div>
    </div>
  );
}
