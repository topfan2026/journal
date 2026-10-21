import type { OptionLeg, OptionQuote, OptionRight } from './types';

const SQRT2PI = Math.sqrt(2 * Math.PI);

function normCdf(x: number): number {
  // Abramowitz–Stegun 26.2.17
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = Math.exp((-x * x) / 2) / SQRT2PI;
  const p = d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return x >= 0 ? 1 - p : p;
}

export function blackScholes(right: OptionRight, S: number, K: number, T: number, sigma: number, r = 0.045) {
  if (T <= 0) {
    const intrinsic = right === 'C' ? Math.max(S - K, 0) : Math.max(K - S, 0);
    return { price: intrinsic, delta: right === 'C' ? (S > K ? 1 : 0) : S < K ? -1 : 0 };
  }
  const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * T) / (sigma * Math.sqrt(T));
  const d2 = d1 - sigma * Math.sqrt(T);
  if (right === 'C') {
    return { price: S * normCdf(d1) - K * Math.exp(-r * T) * normCdf(d2), delta: normCdf(d1) };
  }
  return { price: K * Math.exp(-r * T) * normCdf(-d2) - S * normCdf(-d1), delta: normCdf(d1) - 1 };
}

export function strikeStep(price: number): number {
  if (price < 25) return 0.5;
  if (price < 100) return 1;
  if (price < 250) return 2.5;
  if (price < 1000) return 5;
  return 10;
}

/** Simulated chain around spot with a volatility smile. `jitter` adds live bid/ask movement. */
export function buildChain(spot: number, baseIv: number, dte: number, jitter: () => number = () => 0.5): { strikes: number[]; calls: OptionQuote[]; puts: OptionQuote[] } {
  const step = strikeStep(spot);
  const atm = Math.round(spot / step) * step;
  const strikes: number[] = [];
  for (let i = -10; i <= 10; i++) strikes.push(+(atm + i * step).toFixed(2));
  const T = Math.max(dte, 0.5) / 365;
  const quote = (right: OptionRight, K: number): OptionQuote => {
    const m = Math.log(K / spot);
    const iv = baseIv * (1 + 1.8 * m * m - (right === 'P' ? 0.25 : 0.1) * m);
    const { price, delta } = blackScholes(right, spot, K, T, iv);
    const mid = Math.max(price, 0.01);
    const spread = Math.max(0.01, mid * 0.02 + 0.02) * (0.8 + jitter() * 0.4);
    return {
      strike: K, right, iv, delta,
      mid: round(mid),
      bid: round(Math.max(mid - spread / 2, 0)),
      ask: round(mid + spread / 2),
    };
  };
  return { strikes, calls: strikes.map((k) => quote('C', k)), puts: strikes.map((k) => quote('P', k)) };
}

/** P&L at expiration for the whole strategy, in dollars (100x multiplier). */
export function payoffAt(legs: OptionLeg[], S: number): number {
  return legs.reduce((acc, l) => {
    const intrinsic = l.right === 'C' ? Math.max(S - l.strike, 0) : Math.max(l.strike - S, 0);
    return acc + (intrinsic - l.premium) * l.qty * 100;
  }, 0);
}

export interface StrategyStats {
  maxProfit: number; // Infinity when unbounded
  maxLoss: number; // -Infinity when unbounded
  breakevens: number[];
  netDebit: number; // + debit, - credit (dollars)
  zones: { from: number; to: number; profit: boolean }[];
}

export function analyze(legs: OptionLeg[], lo: number, hi: number): StrategyStats {
  const netDebit = legs.reduce((a, l) => a + l.premium * l.qty * 100, 0);
  if (!legs.length) return { maxProfit: 0, maxLoss: 0, breakevens: [], netDebit: 0, zones: [] };
  // Payoff is piecewise linear with kinks at strikes, so evaluate at kinks + range ends.
  const strikes = [...new Set(legs.map((l) => l.strike))].sort((a, b) => a - b);
  const pts = [Math.min(lo, strikes[0] * 0.5), ...strikes, Math.max(hi, strikes[strikes.length - 1] * 1.5)];
  const vals = pts.map((p) => payoffAt(legs, p));
  const slopeHigh = legs.reduce((a, l) => a + (l.right === 'C' ? l.qty : 0), 0);
  const slopeLow = legs.reduce((a, l) => a + (l.right === 'P' ? -l.qty : 0), 0); // dP/dS as S→0
  let maxProfit = Math.max(...vals);
  let maxLoss = Math.min(...vals);
  if (slopeHigh > 0) maxProfit = Infinity;
  if (slopeHigh < 0) maxLoss = -Infinity;
  // As S decreases to 0 the payoff is bounded; vals[0] near 0.5*min strike captures it adequately,
  // but evaluate exactly at S=0 to be precise.
  const atZero = payoffAt(legs, 0);
  if (slopeLow !== 0) { maxProfit = Math.max(maxProfit, atZero); maxLoss = Math.min(maxLoss, atZero); }

  const breakevens: number[] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = vals[i], b = vals[i + 1];
    if ((a < 0 && b > 0) || (a > 0 && b < 0)) breakevens.push(round(pts[i] + ((0 - a) * (pts[i + 1] - pts[i])) / (b - a)));
    else if (b === 0 && i + 1 < pts.length - 1) breakevens.push(round(pts[i + 1]));
  }
  const uniq = [...new Set(breakevens)].sort((x, y) => x - y);
  const edges = [0, ...uniq, Number.MAX_SAFE_INTEGER];
  const zones = edges.slice(0, -1).map((from, i) => {
    const to = edges[i + 1];
    const probe = to === Number.MAX_SAFE_INTEGER ? from * 1.1 + 1 : (from + to) / 2;
    return { from, to, profit: payoffAt(legs, probe) > 0 };
  });
  return { maxProfit, maxLoss, breakevens: uniq, netDebit, zones };
}

export type PresetName = 'Long Call' | 'Long Put' | 'Bull Call Spread' | 'Bear Put Spread' | 'Iron Condor' | 'Straddle' | 'Strangle' | 'Covered Call*';

export const PRESETS: PresetName[] = ['Long Call', 'Long Put', 'Bull Call Spread', 'Bear Put Spread', 'Iron Condor', 'Straddle', 'Strangle'];

/** Leg templates as (right, strike-offset-in-steps, qty). */
export function presetLegs(name: PresetName): [OptionRight, number, number][] {
  switch (name) {
    case 'Long Call': return [['C', 0, 1]];
    case 'Long Put': return [['P', 0, 1]];
    case 'Bull Call Spread': return [['C', 0, 1], ['C', 2, -1]];
    case 'Bear Put Spread': return [['P', 0, 1], ['P', -2, -1]];
    case 'Iron Condor': return [['P', -4, 1], ['P', -2, -1], ['C', 2, -1], ['C', 4, 1]];
    case 'Straddle': return [['C', 0, 1], ['P', 0, 1]];
    case 'Strangle': return [['C', 2, 1], ['P', -2, 1]];
    default: return [];
  }
}

const round = (n: number) => Math.round(n * 100) / 100;
