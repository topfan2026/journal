import { useEffect, useMemo, useState } from 'react';
import { Eye, EyeOff, Trash2 } from 'lucide-react';
import { useMarket, lastPrice } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { infoFor } from '../data/universe';
import { analyze, buildChain, payoffAt, PRESETS, presetLegs, strikeStep, type PresetName } from '../lib/options';
import type { OptionLeg, OptionQuote, OptionRight } from '../lib/types';
import { orderId } from '../lib/paper';
import { usd } from '../lib/format';
import { Stat, inputCls } from './ui';

const DTES = [7, 14, 30, 45, 60, 90];

export function OptionsPanel() {
  const symbol = useWorkspace((s) => s.symbol);
  const strategy = useWorkspace((s) => s.strategy);
  const setWs = useWorkspace((s) => s.set);
  const spot = useMarket((s) => lastPrice(s.bars[symbol]));
  const [tick, setTick] = useState(0);

  // streaming bid/ask simulation: re-quote the chain every 1.5s
  useEffect(() => { const id = setInterval(() => setTick((t) => t + 1), 1500); return () => clearInterval(id); }, []);
  const dte = strategy.dte;
  const iv = infoFor(symbol).vol;
  const chain = useMemo(() => buildChain(spot, iv, dte, Math.random), [spot, iv, dte, tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const legs = strategy.symbol === symbol ? strategy.legs : [];
  const setLegs = (l: OptionLeg[]) => setWs('strategy', { ...strategy, symbol, legs: l });
  const quote = (right: OptionRight, strike: number): OptionQuote | undefined =>
    (right === 'C' ? chain.calls : chain.puts).find((q) => q.strike === strike);

  // keep leg premiums marked to the live mid for the risk graph
  const marked = legs.map((l) => ({ ...l, premium: quote(l.right, l.strike)?.mid ?? l.premium }));
  const stats = useMemo(() => analyze(marked, spot * 0.6, spot * 1.4), [JSON.stringify(marked), spot]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyPreset = (p: PresetName) => {
    const step = strikeStep(spot);
    const atm = Math.round(spot / step) * step;
    setLegs(presetLegs(p).map(([right, off, qty]) => {
      const strike = +(atm + off * step).toFixed(2);
      return { id: orderId(), right, strike, qty, premium: quote(right, strike)?.mid ?? 0 };
    }));
  };
  const toggleLeg = (right: OptionRight, strike: number, qty: number) => {
    const existing = legs.find((l) => l.right === right && l.strike === strike);
    if (existing) {
      const nq = existing.qty + qty;
      setLegs(nq === 0 ? legs.filter((l) => l !== existing) : legs.map((l) => (l === existing ? { ...l, qty: nq } : l)));
    } else {
      setLegs([...legs, { id: orderId(), right, strike, qty, premium: quote(right, strike)?.mid ?? 0 }]);
    }
  };
  const legQty = (right: OptionRight, strike: number) => legs.find((l) => l.right === right && l.strike === strike)?.qty ?? 0;

  return (
    <div className="flex h-full flex-col text-xs">
      <div className="space-y-2 border-b border-ink-800 p-2">
        <div className="flex flex-wrap gap-1">
          {PRESETS.map((p) => (
            <button key={p} onClick={() => applyPreset(p)} className="rounded border border-ink-700 px-2 py-1 text-2xs text-ink-300 hover:border-accent hover:text-ink-100">{p}</button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-2xs uppercase text-ink-500">Expiry</span>
          <select className={inputCls} value={dte} onChange={(e) => setWs('strategy', { ...strategy, dte: +e.target.value })}>
            {DTES.map((d) => <option key={d} value={d}>{d} DTE</option>)}
          </select>
          <span className="font-mono text-2xs text-ink-400">IV {(iv * 100).toFixed(0)}%</span>
          <button
            className={`ml-auto flex items-center gap-1 rounded px-2 py-1 text-2xs ${strategy.showOnChart ? 'bg-yellow-400/15 text-yellow-300' : 'text-ink-400'}`}
            onClick={() => setWs('strategy', { ...strategy, showOnChart: !strategy.showOnChart })}
          >
            {strategy.showOnChart ? <Eye size={12} /> : <EyeOff size={12} />} P&amp;L zones on chart
          </button>
        </div>
      </div>

      {legs.length > 0 && (
        <div className="space-y-2 border-b border-ink-800 p-2">
          <PayoffChart legs={marked} spot={spot} breakevens={stats.breakevens} />
          <div className="grid grid-cols-3 gap-1.5">
            <Stat label="Max profit" value={stats.maxProfit === Infinity ? 'Unlimited' : usd(stats.maxProfit, 0)} className="text-up" />
            <Stat label="Max loss" value={stats.maxLoss === -Infinity ? 'Unlimited' : usd(stats.maxLoss, 0)} className="text-down" />
            <Stat label={stats.netDebit >= 0 ? 'Net debit' : 'Net credit'} value={usd(Math.abs(stats.netDebit), 0)} />
          </div>
          <div className="font-mono text-2xs text-yellow-300">Breakeven: {stats.breakevens.map((b) => b.toFixed(2)).join(' / ') || '—'}</div>
          <div className="space-y-0.5">
            {marked.map((l) => (
              <div key={l.id} className="flex items-center gap-2 font-mono text-2xs">
                <span className={l.qty > 0 ? 'w-10 text-up' : 'w-10 text-down'}>{l.qty > 0 ? `+${l.qty}` : l.qty}</span>
                <span className="w-24 text-ink-100">{symbol} {l.strike} {l.right === 'C' ? 'Call' : 'Put'}</span>
                <span className="text-ink-400">@ {l.premium.toFixed(2)}</span>
                <button className="ml-auto text-ink-500 hover:text-down" onClick={() => setLegs(legs.filter((x) => x.id !== l.id))} aria-label="Remove leg"><Trash2 size={11} /></button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full font-mono text-2xs">
          <thead className="sticky top-0 bg-ink-950 text-ink-500">
            <tr><th colSpan={3} className="py-1 text-up">CALLS</th><th className="py-1">Strike</th><th colSpan={3} className="py-1 text-down">PUTS</th></tr>
            <tr className="text-right"><th className="px-1">Δ</th><th className="px-1">Bid</th><th className="px-1">Ask</th><th className="text-center">{spot.toFixed(2)}</th><th className="px-1 text-left">Bid</th><th className="px-1 text-left">Ask</th><th className="px-1 text-left">Δ</th></tr>
          </thead>
          <tbody>
            {chain.strikes.map((k, i) => {
              const c = chain.calls[i], p = chain.puts[i];
              const itmC = k < spot, itmP = k > spot;
              return (
                <tr key={k} className="border-t border-ink-800/60">
                  <td className={`px-1 text-right text-ink-500 ${itmC ? 'bg-up/5' : ''}`}>{c.delta.toFixed(2)}</td>
                  <ChainCell q={c} side="bid" qty={legQty('C', k)} onClick={() => toggleLeg('C', k, -1)} itm={itmC} />
                  <ChainCell q={c} side="ask" qty={legQty('C', k)} onClick={() => toggleLeg('C', k, 1)} itm={itmC} />
                  <td className="bg-ink-850 px-2 text-center font-semibold text-ink-100">{k}</td>
                  <ChainCell q={p} side="bid" qty={legQty('P', k)} onClick={() => toggleLeg('P', k, -1)} itm={itmP} />
                  <ChainCell q={p} side="ask" qty={legQty('P', k)} onClick={() => toggleLeg('P', k, 1)} itm={itmP} />
                  <td className={`px-1 text-ink-500 ${itmP ? 'bg-down/5' : ''}`}>{p.delta.toFixed(2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="p-2 text-2xs text-ink-500">Click an <b>Ask</b> to buy a contract or a <b>Bid</b> to sell one. Quotes are simulated (Black-Scholes with a volatility smile).</p>
      </div>
    </div>
  );
}

function ChainCell({ q, side, qty, onClick, itm }: { q: OptionQuote; side: 'bid' | 'ask'; qty: number; onClick: () => void; itm: boolean }) {
  const active = side === 'ask' ? qty > 0 : qty < 0;
  return (
    <td onClick={onClick} className={`cursor-pointer px-1 ${q.right === 'C' ? 'text-right' : ''} ${itm ? (q.right === 'C' ? 'bg-up/5' : 'bg-down/5') : ''} ${active ? (side === 'ask' ? 'bg-up/30 text-ink-100' : 'bg-down/30 text-ink-100') : 'text-ink-300 hover:bg-ink-700'}`}>
      {q[side].toFixed(2)}
    </td>
  );
}

function PayoffChart({ legs, spot, breakevens }: { legs: OptionLeg[]; spot: number; breakevens: number[] }) {
  const W = 320, H = 110;
  const lo = spot * 0.8, hi = spot * 1.2;
  const pts = Array.from({ length: 81 }, (_, i) => { const s = lo + ((hi - lo) * i) / 80; return { s, v: payoffAt(legs, s) }; });
  const vmax = Math.max(...pts.map((p) => Math.abs(p.v)), 1);
  const x = (s: number) => ((s - lo) / (hi - lo)) * W;
  const y = (v: number) => H / 2 - (v / vmax) * (H / 2 - 6);
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.s).toFixed(1)},${y(p.v).toFixed(1)}`).join('');
  const area = `${path}L${W},${H / 2}L0,${H / 2}Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-[110px] w-full rounded bg-ink-950">
      <defs>
        <clipPath id="above"><rect x="0" y="0" width={W} height={H / 2} /></clipPath>
        <clipPath id="below"><rect x="0" y={H / 2} width={W} height={H / 2} /></clipPath>
      </defs>
      <path d={area} fill="rgba(34,197,94,0.25)" clipPath="url(#above)" />
      <path d={area} fill="rgba(239,68,68,0.25)" clipPath="url(#below)" />
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="#344052" />
      <path d={path} fill="none" stroke="#e6ebf2" strokeWidth="1.5" />
      <line x1={x(spot)} x2={x(spot)} y1="0" y2={H} stroke="#3b82f6" strokeDasharray="3 3" />
      {breakevens.filter((b) => b > lo && b < hi).map((b) => <line key={b} x1={x(b)} x2={x(b)} y1="0" y2={H} stroke="#facc15" strokeDasharray="4 3" />)}
      <text x="4" y="11" fill="#8592a8" fontSize="9">P&amp;L at expiration</text>
    </svg>
  );
}
