import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useMarket, lastPrice } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { infoFor } from '../data/universe';
import { buildChain } from '../lib/options';
import { shortExpiry, upcomingExpirations } from '../lib/expirations';
import { hashString, mulberry32 } from '../lib/random';
import { compactNum } from '../lib/format';
import { orderId } from '../lib/paper';
import type { OptionRight } from '../lib/types';
import { PanelHeader } from './ui';

const DAY_RANGES = [30, 60, 100, 180, 365];

/** Option chain window: expirations grouped with days remaining, streaming bid/ask. Click a row to add it to the strategy. */
export function OptionChainPanel() {
  const symbol = useWorkspace((s) => s.symbol);
  const strategy = useWorkspace((s) => s.strategy);
  const setWs = useWorkspace((s) => s.set);
  const toast = useWorkspace((s) => s.toast);
  const spot = useMarket((s) => lastPrice(s.bars[symbol]));
  const [days, setDays] = useState(100);
  const [strikes, setStrikes] = useState(6);
  const [which, setWhich] = useState<'C' | 'P' | 'CP'>('CP');
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [tick, setTick] = useState(0);
  useEffect(() => { const id = setInterval(() => setTick((t) => t + 1), 1500); return () => clearInterval(id); }, []);

  const iv = infoFor(symbol).vol;
  const exps = useMemo(() => upcomingExpirations(days), [days]);
  const groups = useMemo(() => exps.flatMap((e) => {
    const chain = buildChain(spot, iv, e.dte, Math.random);
    const atm = chain.strikes.reduce((best, k, i) => (Math.abs(k - spot) < Math.abs(chain.strikes[best] - spot) ? i : best), 0);
    const idx = chain.strikes.map((_, i) => i).filter((i) => Math.abs(i - atm) <= strikes);
    const rights: OptionRight[] = which === 'CP' ? ['C', 'P'] : [which];
    return rights.map((right) => ({
      key: `${e.label}-${right}`, e, right,
      rows: idx.map((i) => {
        const q = right === 'C' ? chain.calls[i] : chain.puts[i];
        const intrinsic = right === 'C' ? Math.max(spot - q.strike, 0) : Math.max(q.strike - spot, 0);
        // stable pseudo volume / open interest, heavier near the money and near expiry
        const r = mulberry32(hashString(`${symbol}${e.label}${right}${q.strike}`));
        const nearness = Math.exp(-Math.abs(i - atm) / 3);
        const oi = Math.round((200 + r() * 3000) * nearness * (1 + 20 / (e.dte + 5)));
        const vol = Math.round(oi * (0.05 + r() * 0.3) * (0.9 + Math.random() * 0.2));
        return { ...q, timeVal: Math.max(q.mid - intrinsic, 0), vol, oi };
      }),
    }));
  }), [exps, spot, iv, strikes, which, symbol, tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const addLeg = (right: OptionRight, strike: number, dte: number, ask: number) => {
    const legs = strategy.symbol === symbol ? strategy.legs : [];
    setWs('strategy', { ...strategy, symbol, dte, legs: [...legs, { id: orderId(), right, strike, qty: 1, premium: ask }] });
    toast(`Added +1 ${symbol} ${strike} ${right === 'C' ? 'Call' : 'Put'} (${dte} DTE) to the strategy — see the Options page`);
  };

  return (
    <div className="flex h-full flex-col bg-[#0b0e13] text-xs">
      <PanelHeader>
        <span className="font-semibold text-ink-100">{symbol}</span>
        <select className="ml-2 bg-transparent text-2xs text-ink-300 outline-none" value={days} onChange={(e) => setDays(+e.target.value)}>
          {DAY_RANGES.map((d) => <option key={d} value={d} className="bg-ink-900">{d} Days</option>)}
        </select>
        <select className="bg-transparent text-2xs text-ink-300 outline-none" value={strikes} onChange={(e) => setStrikes(+e.target.value)}>
          {[2, 4, 6, 8, 10].map((n) => <option key={n} value={n} className="bg-ink-900">Strikes {n}</option>)}
        </select>
        <select className="bg-transparent text-2xs text-ink-300 outline-none" value={which} onChange={(e) => setWhich(e.target.value as typeof which)}>
          <option value="CP" className="bg-ink-900">Calls &amp; Puts</option><option value="C" className="bg-ink-900">Calls</option><option value="P" className="bg-ink-900">Puts</option>
        </select>
        <span className="ml-auto font-mono text-2xs text-ink-500">{spot.toFixed(2)}</span>
      </PanelHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full font-mono text-2xs">
          <thead className="sticky top-0 z-10 bg-ink-950 text-ink-500">
            <tr className="text-right"><th className="px-1.5 py-1 text-left font-sans">Sym</th><th className="px-1.5">Bid</th><th className="px-1.5">Ask</th><th className="px-1.5">Time Val</th><th className="px-1.5">Volume</th><th className="px-1.5">Open Int</th></tr>
          </thead>
          {groups.map((g) => (
            <tbody key={g.key}>
              <tr className="cursor-pointer bg-ink-900" onClick={() => setCollapsed((c) => ({ ...c, [g.key]: !c[g.key] }))}>
                <td colSpan={6} className="px-1.5 py-0.5 text-center font-sans font-semibold text-blue-300">
                  {collapsed[g.key] ? <ChevronRight size={10} className="inline" /> : <ChevronDown size={10} className="inline" />}{' '}
                  {symbol} - {g.e.label} {g.right === 'C' ? 'Call' : 'Put'} - {g.e.dte} day{g.e.dte === 1 ? '' : 's'} remaining
                </td>
              </tr>
              {!collapsed[g.key] && g.rows.map((r) => {
                const itm = g.right === 'C' ? r.strike < spot : r.strike > spot;
                return (
                  <tr key={r.strike} onClick={() => addLeg(g.right, r.strike, g.e.dte, r.ask)} title="Click to add to strategy"
                    className={`cursor-pointer border-b border-ink-850 text-right hover:bg-ink-800 ${itm ? 'bg-ink-850/60' : ''}`}>
                    <td className="px-1.5 py-0.5 text-left text-ink-100">{shortExpiry(g.e)} {g.right} {r.strike.toFixed(2)}</td>
                    <td className="px-1.5">{r.bid.toFixed(2)}</td>
                    <td className="px-1.5">{r.ask.toFixed(2)}</td>
                    <td className="px-1.5 font-semibold text-ink-100">{r.timeVal.toFixed(2)}</td>
                    <td className="px-1.5 text-ink-300">{compactNum(r.vol)}</td>
                    <td className="px-1.5 text-ink-300">{compactNum(r.oi)}</td>
                  </tr>
                );
              })}
            </tbody>
          ))}
        </table>
      </div>
      <div className="flex h-5 shrink-0 items-center border-t border-ink-800 px-2 text-[10px] text-ink-500">
        {groups.reduce((a, g) => a + g.rows.length, 0)} contracts · simulated quotes
      </div>
    </div>
  );
}
