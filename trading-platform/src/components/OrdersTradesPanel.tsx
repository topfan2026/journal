import { useState } from 'react';
import { X } from 'lucide-react';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { usd, tone } from '../lib/format';
import type { Order } from '../lib/types';
import { PanelHeader } from './ui';

const time = (t?: number) => (t ? new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '');

/** Orders & Trades window with TC2000-style columns. Bracket children show their OCA group and parent state. */
export function OrdersTradesPanel() {
  const { paper, cancelOrder, setSymbol } = useWorkspace();
  const bars = useMarket((s) => s.bars);
  const [tab, setTab] = useState<'orders' | 'trades'>('orders');
  const [scope, setScope] = useState<'active' | 'all'>('active');
  const last = (s: string) => bars[s]?.[bars[s].length - 1]?.close ?? 0;

  const orders = paper.orders.filter((o) => (scope === 'active' ? o.status === 'WORKING' : true)).slice().reverse();
  const trades = paper.orders.filter((o) => o.status === 'FILLED').sort((a, b) => (b.filledAt ?? 0) - (a.filledAt ?? 0));

  const details = (o: Order) => {
    const px = o.type === 'TRAIL' ? `trail $${o.trailAmount}` : o.price !== undefined ? `@ ${o.price.toFixed(2)}` : '';
    const parent = o.parentId ? paper.orders.find((p) => p.id === o.parentId) : undefined;
    return `${o.type} ${px}${o.label ? ` · ${o.label}` : ''}${parent && parent.status !== 'FILLED' ? ' · waits for entry' : ''}`;
  };
  const dist = (o: Order) => (o.price !== undefined && last(o.symbol) ? ((o.price - last(o.symbol)) / last(o.symbol)) * 100 : null);
  const estPl = (o: Order) => {
    const pos = paper.positions[o.symbol];
    if (!pos || o.price === undefined || Math.sign(pos.qty) === (o.side === 'BUY' ? 1 : -1)) return null;
    return (o.price - pos.avgPrice) * Math.min(o.qty, Math.abs(pos.qty)) * Math.sign(pos.qty);
  };

  return (
    <div className="flex h-full flex-col bg-[#0b0e13] text-xs">
      <PanelHeader>
        {(['orders', 'trades'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`rounded px-2 py-0.5 capitalize ${tab === t ? 'bg-ink-700 text-ink-100' : 'text-ink-400 hover:text-ink-100'}`}>{t}</button>
        ))}
        {tab === 'orders' && (
          <select className="ml-2 bg-transparent text-2xs text-ink-300 outline-none" value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
            <option value="active" className="bg-ink-900">Active orders</option><option value="all" className="bg-ink-900">All orders today</option>
          </select>
        )}
      </PanelHeader>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full whitespace-nowrap font-mono text-2xs">
          {tab === 'orders' ? (
            <>
              <thead className="sticky top-0 bg-ink-950 text-ink-500">
                <tr className="text-right">
                  <th className="px-2 py-1 text-left font-sans">Sym</th><th className="px-2">Last</th><th className="px-2 text-left">B/S</th><th className="px-2">Qty</th>
                  <th className="px-2">Est Amt</th><th className="px-2">Dist</th><th className="px-2">Est P&amp;L</th><th className="px-2 text-left">Status</th>
                  <th className="px-2 text-left">OCA</th><th className="px-2 text-left">Details</th><th className="px-2 text-left">TIF</th><th className="px-2">Placed</th><th className="px-2">Fill Pr</th><th />
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => {
                  const d = dist(o), pl = estPl(o);
                  return (
                    <tr key={o.id} onClick={() => setSymbol(o.symbol)} className="cursor-pointer border-b border-ink-850 text-right hover:bg-ink-850">
                      <td className="px-2 py-1 text-left font-sans font-semibold text-ink-100">{o.symbol}</td>
                      <td className="px-2">{last(o.symbol).toFixed(2)}</td>
                      <td className={`px-2 text-left ${o.side === 'BUY' ? 'text-up' : 'text-down'}`}>{o.side === 'BUY' ? 'Buy' : 'Sell'}</td>
                      <td className="px-2">{o.qty}</td>
                      <td className="px-2">{usd(o.qty * (o.price ?? last(o.symbol)), 0)}</td>
                      <td className="px-2">{d === null ? '' : `${d >= 0 ? '+' : ''}${d.toFixed(2)}%`}</td>
                      <td className={`px-2 ${tone(pl ?? 0)}`}>{pl === null ? '' : usd(pl, 0)}</td>
                      <td className={`px-2 text-left font-sans ${o.status === 'WORKING' ? 'text-blue-300' : o.status === 'FILLED' ? 'text-up' : 'text-ink-500'}`}>{o.status === 'WORKING' ? 'Working' : o.status === 'FILLED' ? 'Filled' : 'Cancelled'}</td>
                      <td className="px-2 text-left font-sans">{o.ocaGroup ? <span className="rounded bg-purple-500/15 px-1 text-purple-300">OCA</span> : ''}</td>
                      <td className="px-2 text-left font-sans text-ink-300">{details(o)}</td>
                      <td className="px-2 text-left font-sans text-ink-400">GTC</td>
                      <td className="px-2 text-ink-400">{time(o.createdAt)}</td>
                      <td className="px-2">{o.fillPrice?.toFixed(2) ?? ''}</td>
                      <td className="px-1">{o.status === 'WORKING' && <button onClick={(e) => { e.stopPropagation(); cancelOrder(o.id); }} className="text-ink-500 hover:text-down" aria-label="Cancel order"><X size={11} /></button>}</td>
                    </tr>
                  );
                })}
                {!orders.length && <tr><td colSpan={14} className="p-4 text-center font-sans text-ink-500">No {scope === 'active' ? 'active ' : ''}orders</td></tr>}
              </tbody>
            </>
          ) : (
            <>
              <thead className="sticky top-0 bg-ink-950 text-ink-500">
                <tr className="text-right"><th className="px-2 py-1 text-left font-sans">Time</th><th className="px-2 text-left font-sans">Sym</th><th className="px-2 text-left">B/S</th><th className="px-2">Qty</th><th className="px-2">Price</th><th className="px-2">Amount</th><th className="px-2 text-left font-sans">Via</th></tr>
              </thead>
              <tbody>
                {trades.map((o) => (
                  <tr key={o.id} className="border-b border-ink-850 text-right">
                    <td className="px-2 py-1 text-left text-ink-400">{time(o.filledAt)}</td>
                    <td className="px-2 text-left font-sans font-semibold text-ink-100">{o.symbol}</td>
                    <td className={`px-2 text-left ${o.side === 'BUY' ? 'text-up' : 'text-down'}`}>{o.side === 'BUY' ? 'Buy' : 'Sell'}</td>
                    <td className="px-2">{o.qty}</td><td className="px-2">{o.fillPrice?.toFixed(2)}</td>
                    <td className="px-2">{usd((o.fillPrice ?? 0) * o.qty, 0)}</td>
                    <td className="px-2 text-left font-sans text-ink-400">{o.label ?? o.type}</td>
                  </tr>
                ))}
                {!trades.length && <tr><td colSpan={7} className="p-4 text-center font-sans text-ink-500">No trades yet</td></tr>}
              </tbody>
            </>
          )}
        </table>
      </div>
      <div className="flex h-5 shrink-0 items-center border-t border-ink-800 px-2 text-[10px] text-ink-500">
        {tab === 'orders' ? `${orders.length} orders` : `${trades.length} trades`} · paper account
      </div>
    </div>
  );
}
