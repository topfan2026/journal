import { useEffect, useState } from 'react';
import { RotateCcw } from 'lucide-react';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { ibkr, type IbkrPosition } from '../lib/ibkr';
import { dayPnl } from '../lib/paper';
import { usd, tone } from '../lib/format';
import { PanelHeader } from './ui';

/** Positions window. Paper mode shows the simulated account; Live mode shows IBKR positions (read-only). */
export function PositionsPanel() {
  const mode = useWorkspace((s) => s.mode);
  const { paper, setSymbol, resetPaper } = useWorkspace();
  const bars = useMarket((s) => s.bars);
  const prev = useMarket((s) => s.prevClose);
  const [livePos, setLivePos] = useState<IbkrPosition[] | null>(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (mode !== 'live') return;
    let alive = true;
    const load = () => ibkr.positions().then((p) => { if (alive) { setLivePos(p); setErr(''); } }).catch((e) => alive && setErr(String(e.message ?? e)));
    load();
    const id = setInterval(load, 10000);
    return () => { alive = false; clearInterval(id); };
  }, [mode]);

  const last = (s: string) => bars[s]?.[bars[s].length - 1]?.close ?? 0;
  const working = (s: string) => paper.orders.filter((o) => o.symbol === s && o.status === 'WORKING').length;

  const rows = mode === 'live'
    ? (livePos ?? []).map((p) => ({ symbol: p.symbol, qty: p.qty, entry: p.avgPrice, last: p.mktPrice, day: null as number | null, unreal: p.unrealizedPnl, orders: 0 }))
    : Object.values(paper.positions).map((p) => ({
      symbol: p.symbol, qty: p.qty, entry: p.avgPrice, last: last(p.symbol),
      day: dayPnl(p, last(p.symbol), prev[p.symbol]),
      unreal: (last(p.symbol) - p.avgPrice) * p.qty, orders: working(p.symbol),
    }));

  return (
    <div className="flex h-full flex-col bg-[#0b0e13] text-xs">
      <PanelHeader>
        <span className="font-semibold text-ink-100">Positions</span>
        <span className={`ml-2 rounded px-1 text-2xs ${mode === 'live' ? 'bg-up/15 text-up' : 'bg-warn/15 text-warn'}`}>{mode === 'live' ? 'IBKR · read-only' : 'Paper'}</span>
        {mode === 'paper' && (
          <button onClick={() => confirm('Reset the paper account to $100,000?') && resetPaper()} className="ml-auto flex items-center gap-1 text-2xs text-ink-500 hover:text-ink-100"><RotateCcw size={10} /> Reset</button>
        )}
      </PanelHeader>
      <div className="min-h-0 flex-1 overflow-auto">
        {err ? <div className="p-3 text-2xs text-down">Can't reach IBKR: {err}</div> : (
          <table className="w-full font-mono text-2xs">
            <thead className="sticky top-0 bg-ink-950 text-ink-500">
              <tr className="text-right">
                <th className="px-2 py-1 text-left font-sans">Sym</th><th className="px-2">Day P&amp;L</th><th className="px-2">Pos</th><th className="px-2">Mkt Val</th>
                <th className="px-2">Unreal P&amp;L</th><th className="px-2">Unreal %</th><th className="px-2">Entry</th><th className="px-2">#Ord</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const cost = Math.abs(r.entry * r.qty);
                return (
                  <tr key={r.symbol} onClick={() => setSymbol(r.symbol)} className="cursor-pointer border-b border-ink-850 text-right hover:bg-ink-850">
                    <td className="px-2 py-1 text-left font-sans font-semibold text-ink-100">{r.symbol}</td>
                    <td className={`px-2 ${tone(r.day ?? 0)}`}>{r.day === null ? '—' : usd(r.day, 0)}</td>
                    <td className={`px-2 ${tone(r.qty)}`}>{r.qty}</td>
                    <td className="px-2">{usd(r.last * r.qty, 0)}</td>
                    <td className={`px-2 ${tone(r.unreal)}`}>{usd(r.unreal, 0)}</td>
                    <td className={`px-2 ${tone(r.unreal)}`}>{cost ? `${((r.unreal / cost) * 100).toFixed(2)}%` : '—'}</td>
                    <td className="px-2">{r.entry.toFixed(2)}</td>
                    <td className="px-2">{r.orders || ''}</td>
                  </tr>
                );
              })}
              {!rows.length && <tr><td colSpan={8} className="p-4 text-center font-sans text-ink-500">No open positions</td></tr>}
            </tbody>
          </table>
        )}
      </div>
      <div className="flex h-5 shrink-0 items-center border-t border-ink-800 px-2 text-[10px] text-ink-500">
        {rows.length} items · realized {usd(paper.realized, 0)}
      </div>
    </div>
  );
}
