import { useMarket, tfKey } from '../store/market';
import { useWorkspace, type ForwardTest } from '../store/workspace';
import { computeSeries, evaluateAt } from './scanner';
import { buildBracket, orderId } from './paper';
import { infoFor } from '../data/universe';
import type { Order } from './types';

export const ftTag = (t: ForwardTest) => `ft:${t.id}`;

/** Net shares and cash flow of the filled orders a forward test placed for one symbol. */
export function ftPosition(orders: Order[], tag: string, symbol: string) {
  let qty = 0, cash = 0;
  for (const o of orders) {
    if (o.tag !== tag || o.symbol !== symbol || o.status !== 'FILLED' || o.fillPrice === undefined) continue;
    const signed = o.side === 'BUY' ? o.qty : -o.qty;
    qty += signed;
    cash -= signed * o.fillPrice;
  }
  return { qty, cash };
}

/**
 * Runs every active forward test against the latest bars. Signals are evaluated on the live
 * (still-forming) bar; each bar can trigger at most one entry and one exit per symbol.
 * Trades go to the paper account, tagged so results can be attributed to the test.
 */
export function stepForwardTests() {
  const ws = useWorkspace.getState();
  const active = ws.forwardTests.filter((t) => t.active);
  if (!active.length) return;
  const market = useMarket.getState();

  for (const t of active) {
    const def = ws.strategies.find((s) => s.id === t.strategyId);
    if (!def) continue;
    const tag = ftTag(t);
    for (const sym of t.symbols) {
      const bars = t.tf === 'D' ? market.bars[sym] : market.tfBars[tfKey(sym, t.tf)];
      if (!bars || bars.length < 30) { market.ensureTf(sym, t.tf); continue; }
      const i = bars.length - 1;
      const barTime = bars[i].time;
      const price = bars[i].close;
      const orders = useWorkspace.getState().paper.orders;
      const { qty } = ftPosition(orders, tag, sym);
      const working = orders.filter((o) => o.tag === tag && o.symbol === sym && o.status === 'WORKING');
      if (t.lastSignal[sym] === barTime) continue;
      const series = computeSeries(bars, infoFor(sym));
      const log = (text: string, tone: 'up' | 'down' | 'info') =>
        ws.updateForwardTest(t.id, (cur) => ({ log: [...cur.log.slice(-199), { time: Date.now(), text, tone }], lastSignal: { ...cur.lastSignal, [sym]: barTime } }));

      if (qty === 0 && !working.some((o) => !o.parentId)) {
        if (!def.entry.length || !def.entry.every((c) => evaluateAt(series, c, i))) continue;
        const shares = def.sizing.mode === 'shares' ? def.sizing.value : Math.floor((def.capital * def.sizing.value) / 100 / price);
        if (shares < 1) continue;
        working.forEach((o) => ws.cancelOrder(o.id)); // leftover exits from a previous trade
        const dir = def.direction === 'long' ? 1 : -1;
        ws.placeOrders(buildBracket({
          symbol: sym, side: dir === 1 ? 'BUY' : 'SELL', qty: shares, entryType: 'MKT', tag,
          stop: def.stopPct ? +(price * (1 - (dir * def.stopPct) / 100)).toFixed(2) : undefined,
          target: def.targetPct ? +(price * (1 + (dir * def.targetPct) / 100)).toFixed(2) : undefined,
          trail: def.trailPct ? +((price * def.trailPct) / 100).toFixed(2) : undefined,
        }));
        ws.onPrice(sym, price);
        ws.updateForwardTest(t.id, (cur) => ({ entryBar: { ...cur.entryBar, [sym]: barTime } }));
        log(`${def.direction === 'long' ? 'BUY' : 'SELL SHORT'} ${shares} ${sym} @ ~${price.toFixed(2)} — entry rules true`, 'up');
      } else if (qty !== 0) {
        const entryBar = useWorkspace.getState().forwardTests.find((x) => x.id === t.id)?.entryBar[sym];
        const held = entryBar === undefined ? 0 : bars.filter((b) => b.time >= entryBar).length;
        const timeUp = def.maxBars ? held >= def.maxBars : false;
        const exitNow = def.exit.length && def.exit.some((c) => evaluateAt(series, c, i));
        if (!exitNow && !timeUp) continue;
        working.forEach((o) => ws.cancelOrder(o.id));
        ws.placeOrders([{ id: orderId(), symbol: sym, side: qty > 0 ? 'SELL' : 'BUY', type: 'MKT', qty: Math.abs(qty), status: 'WORKING', createdAt: Date.now(), label: 'Exit', tag }]);
        ws.onPrice(sym, price);
        log(`EXIT ${Math.abs(qty)} ${sym} @ ~${price.toFixed(2)} — ${timeUp ? `held ${held} bars` : 'exit rule true'}`, 'down');
      }
    }
  }
}
