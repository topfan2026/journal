import type { Order, Position } from './types';

export interface Account {
  cash: number;
  positions: Record<string, Position>;
  orders: Order[];
  realized: number;
}

export const STARTING_CASH = 100_000;
export const newAccount = (): Account => ({ cash: STARTING_CASH, positions: {}, orders: [], realized: 0 });

let seq = 0;
export const orderId = () => `o${Date.now().toString(36)}${(seq++).toString(36)}`;

/** Is the order eligible to trigger (working and, if it is a bracket child, its parent has filled)? */
function active(o: Order, all: Order[]): boolean {
  if (o.status !== 'WORKING') return false;
  if (!o.parentId) return true;
  return all.find((p) => p.id === o.parentId)?.status === 'FILLED';
}

function triggered(o: Order, price: number): boolean {
  switch (o.type) {
    case 'MKT': return true;
    case 'LMT': return o.side === 'BUY' ? price <= (o.price as number) : price >= (o.price as number);
    case 'STP': return o.side === 'BUY' ? price >= (o.price as number) : price <= (o.price as number);
    case 'TRAIL': {
      const anchor = o.trailAnchor as number;
      const dist = o.trailAmount as number;
      return o.side === 'SELL' ? price <= anchor - dist : price >= anchor + dist;
    }
  }
}

function fillPrice(o: Order, price: number): number {
  // Limits fill at the limit or better; stops and markets at the trade price.
  if (o.type === 'LMT') return o.side === 'BUY' ? Math.min(price, o.price as number) : Math.max(price, o.price as number);
  return price;
}

function applyFill(acct: Account, o: Order, px: number, now: number) {
  const signed = o.side === 'BUY' ? o.qty : -o.qty;
  const pos = acct.positions[o.symbol] ?? { symbol: o.symbol, qty: 0, avgPrice: 0, openedAt: now };
  let realized = 0;
  if (pos.qty === 0 || Math.sign(pos.qty) === Math.sign(signed)) {
    const newQty = pos.qty + signed;
    pos.avgPrice = (pos.avgPrice * Math.abs(pos.qty) + px * Math.abs(signed)) / Math.abs(newQty);
    pos.qty = newQty;
  } else {
    const closing = Math.min(Math.abs(signed), Math.abs(pos.qty));
    realized = closing * (px - pos.avgPrice) * Math.sign(pos.qty);
    const newQty = pos.qty + signed;
    if (newQty === 0) pos.avgPrice = 0;
    else if (Math.sign(newQty) !== Math.sign(pos.qty)) { pos.avgPrice = px; pos.openedAt = now; } // flipped
    pos.qty = newQty;
  }
  acct.cash -= signed * px;
  acct.realized += realized;
  if (pos.qty === 0) delete acct.positions[o.symbol];
  else acct.positions[o.symbol] = pos;
}

/**
 * Process a price update for one symbol. Returns a new account plus the orders that filled.
 * Handles bracket activation (children wait on parent), trailing anchors, and OCA cancellation.
 */
export function processPrice(acct: Account, symbol: string, price: number, now = Date.now()): { account: Account; fills: Order[] } {
  const next: Account = { ...acct, positions: { ...acct.positions }, orders: acct.orders.map((o) => ({ ...o })) };
  const fills: Order[] = [];
  // Loop so a parent filling on this tick lets its children be evaluated on the same price.
  for (let pass = 0; pass < 3; pass++) {
    let progressed = false;
    for (const o of next.orders) {
      if (o.symbol !== symbol || !active(o, next.orders)) continue;
      if (o.type === 'TRAIL') {
        if (o.trailAnchor === undefined) o.trailAnchor = price;
        o.trailAnchor = o.side === 'SELL' ? Math.max(o.trailAnchor, price) : Math.min(o.trailAnchor, price);
      }
      if (!triggered(o, price)) continue;
      const px = round(fillPrice(o, price));
      o.status = 'FILLED';
      o.fillPrice = px;
      o.filledAt = now;
      applyFill(next, o, px, now);
      fills.push(o);
      progressed = true;
      if (o.ocaGroup) {
        for (const sib of next.orders) {
          if (sib.id !== o.id && sib.ocaGroup === o.ocaGroup && sib.status === 'WORKING') sib.status = 'CANCELLED';
        }
      }
    }
    if (!progressed) break;
  }
  return { account: next, fills };
}

export interface BracketSpec {
  symbol: string;
  side: 'BUY' | 'SELL';
  qty: number;
  entryType: 'MKT' | 'LMT' | 'STP';
  entryPrice?: number;
  target?: number;
  stop?: number;
  trail?: number;
}

/** Build an entry plus OCA exit legs (target / stop / trailing stop). */
export function buildBracket(spec: BracketSpec, now = Date.now()): Order[] {
  const entry: Order = {
    id: orderId(), symbol: spec.symbol, side: spec.side, type: spec.entryType, qty: spec.qty,
    price: spec.entryType === 'MKT' ? undefined : spec.entryPrice, status: 'WORKING', createdAt: now, label: 'Entry',
  };
  const exitSide = spec.side === 'BUY' ? 'SELL' : 'BUY';
  const oca = `oca-${entry.id}`;
  const children: Order[] = [];
  const child = (type: Order['type'], label: string, extra: Partial<Order>) =>
    children.push({ id: orderId(), symbol: spec.symbol, side: exitSide, type, qty: spec.qty, status: 'WORKING', createdAt: now, parentId: entry.id, ocaGroup: oca, label, ...extra });
  if (spec.target) child('LMT', 'Target', { price: spec.target });
  if (spec.stop) child('STP', 'Stop', { price: spec.stop });
  if (spec.trail) child('TRAIL', 'Trail', { trailAmount: spec.trail });
  return [entry, ...children];
}

export function equity(acct: Account, prices: Record<string, number>): number {
  return Object.values(acct.positions).reduce((a, p) => a + p.qty * (prices[p.symbol] ?? p.avgPrice), acct.cash);
}

const round = (n: number) => Math.round(n * 100) / 100;

/** Day P&L: from entry for positions opened today, otherwise from the prior close. */
export function dayPnl(pos: Position, last: number, prevClose: number | undefined, now = Date.now()): number | null {
  const today = new Date(now).toDateString();
  if (pos.openedAt && new Date(pos.openedAt).toDateString() === today) return (last - pos.avgPrice) * pos.qty;
  return prevClose ? (last - prevClose) * pos.qty : null;
}
