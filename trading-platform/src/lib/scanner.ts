import type { Bar, SymbolInfo } from './types';
import { closes, ema, macd, rsi, sma, stochastic, type Series } from './indicators';

export type Metric =
  | 'price' | 'changePct' | 'rsi14' | 'macdLine' | 'macdSignal' | 'macdHist'
  | 'sma20' | 'sma50' | 'sma200' | 'ema9' | 'ema21' | 'high20' | 'low20' | 'stochK' | 'atr14'
  | 'volumeRatio' | 'epsGrowth' | 'marketCapB';

export const METRIC_LABELS: Record<Metric, string> = {
  price: 'Price', changePct: '% Change', rsi14: 'RSI(14)', macdLine: 'MACD', macdSignal: 'MACD Signal',
  macdHist: 'MACD Histogram', sma20: 'SMA 20', sma50: 'SMA 50', sma200: 'SMA 200',
  ema9: 'EMA 9', ema21: 'EMA 21', high20: 'Prior 20-bar High', low20: 'Prior 20-bar Low', stochK: 'Stochastic %K', atr14: 'ATR(14)',
  volumeRatio: 'Volume / 20d Avg', epsGrowth: 'EPS Growth %', marketCapB: 'Market Cap ($B)',
};

export type Operator = '>' | '<' | 'crossesAbove' | 'crossesBelow';

export interface Condition {
  id: string;
  left: Metric;
  op: Operator;
  right: { kind: 'value'; value: number } | { kind: 'metric'; metric: Metric };
  /** "Flex" — condition must be true on at least `atLeast` of the last `within` bars. */
  flex?: { atLeast: number; within: number };
}

export interface ScanRow {
  symbol: string;
  name: string;
  sector: string;
  price: number;
  changePct: number;
  volume: number;
  rsi14: number | null;
  macdHist: number | null;
  marketCapB: number;
  epsGrowth: number;
}

export type MetricSeries = Record<Metric, Series>;

/** Highest high / lowest low of the `n` bars before i (excludes bar i, so breakouts can trigger). */
function priorExtreme(bars: Bar[], n: number, hi: boolean): Series {
  return bars.map((_, i) => {
    if (i < n) return null;
    let v = hi ? -Infinity : Infinity;
    for (let j = i - n; j < i; j++) v = hi ? Math.max(v, bars[j].high) : Math.min(v, bars[j].low);
    return v;
  });
}

function atr(bars: Bar[], n: number): Series {
  const tr = bars.map((b, i) => (i === 0 ? b.high - b.low : Math.max(b.high - b.low, Math.abs(b.high - bars[i - 1].close), Math.abs(b.low - bars[i - 1].close))));
  const out: Series = new Array(bars.length).fill(null);
  let prev: number | null = null;
  for (let i = 0; i < bars.length; i++) {
    if (i < n - 1) continue;
    prev = prev === null ? tr.slice(0, n).reduce((a, b) => a + b, 0) / n : (prev * (n - 1) + tr[i]) / n;
    out[i] = prev;
  }
  return out;
}

export function computeSeries(bars: Bar[], info: SymbolInfo): MetricSeries {
  const c = closes(bars);
  const m = macd(c);
  const volAvg = sma(bars.map((b) => b.volume), 20);
  return {
    price: c,
    changePct: c.map((v, i) => (i === 0 ? null : ((v - c[i - 1]) / c[i - 1]) * 100)),
    rsi14: rsi(c, 14),
    macdLine: m.line,
    macdSignal: m.signal,
    macdHist: m.hist,
    sma20: sma(c, 20),
    sma50: sma(c, 50),
    sma200: sma(c, 200),
    ema9: ema(c, 9),
    ema21: ema(c, 21),
    high20: priorExtreme(bars, 20, true),
    low20: priorExtreme(bars, 20, false),
    stochK: stochastic(bars).k,
    atr14: atr(bars, 14),
    volumeRatio: bars.map((b, i) => (volAvg[i] ? b.volume / (volAvg[i] as number) : null)),
    epsGrowth: c.map(() => info.epsGrowth),
    marketCapB: c.map(() => info.marketCapB),
  };
}

function rhsAt(s: MetricSeries, cond: Condition, i: number): number | null {
  return cond.right.kind === 'value' ? cond.right.value : s[cond.right.metric][i];
}

function trueAt(s: MetricSeries, cond: Condition, i: number): boolean {
  const l = s[cond.left][i];
  const r = rhsAt(s, cond, i);
  if (l === null || r === null) return false;
  if (cond.op === '>') return l > r;
  if (cond.op === '<') return l < r;
  if (i === 0) return false;
  const pl = s[cond.left][i - 1];
  const pr = rhsAt(s, cond, i - 1);
  if (pl === null || pr === null) return false;
  return cond.op === 'crossesAbove' ? pl <= pr && l > r : pl >= pr && l < r;
}

export function evaluate(s: MetricSeries, cond: Condition): boolean {
  return evaluateAt(s, cond, s.price.length - 1);
}

/** Evaluate a condition as of bar `last` (inclusive), honoring Flex over the bars up to it. */
export function evaluateAt(s: MetricSeries, cond: Condition, last: number): boolean {
  if (last < 0) return false;
  const within = Math.max(1, cond.flex?.within ?? 1);
  const atLeast = Math.min(within, Math.max(1, cond.flex?.atLeast ?? 1));
  let hits = 0;
  for (let i = last; i > last - within && i >= 0; i--) if (trueAt(s, cond, i)) hits++;
  return hits >= atLeast;
}

export function describe(cond: Condition): string {
  const opText = { '>': 'is above', '<': 'is below', crossesAbove: 'crosses above', crossesBelow: 'crosses below' }[cond.op];
  const rhs = cond.right.kind === 'value' ? String(cond.right.value) : METRIC_LABELS[cond.right.metric];
  const flex = cond.flex && cond.flex.within > 1 ? ` (${cond.flex.atLeast} of last ${cond.flex.within} bars)` : '';
  return `${METRIC_LABELS[cond.left]} ${opText} ${rhs}${flex}`;
}

let n = 0;
const cid = () => `c${Date.now().toString(36)}${n++}`;

export const SCAN_PRESETS: { name: string; description: string; conditions: Omit<Condition, 'id'>[] }[] = [
  { name: 'High EPS Growth', description: 'EPS growth above 25%', conditions: [{ left: 'epsGrowth', op: '>', right: { kind: 'value', value: 25 } }] },
  { name: 'Mega Cap', description: 'Market cap above $500B', conditions: [{ left: 'marketCapB', op: '>', right: { kind: 'value', value: 500 } }] },
  { name: 'RSI Oversold Cross', description: 'RSI(14) crossed above 30 in last 5 bars', conditions: [{ left: 'rsi14', op: 'crossesAbove', right: { kind: 'value', value: 30 }, flex: { atLeast: 1, within: 5 } }] },
  { name: 'RSI Overbought', description: 'RSI(14) above 70', conditions: [{ left: 'rsi14', op: '>', right: { kind: 'value', value: 70 } }] },
  { name: 'MACD Breakout', description: 'MACD crossed above signal in last 3 bars', conditions: [{ left: 'macdLine', op: 'crossesAbove', right: { kind: 'metric', metric: 'macdSignal' }, flex: { atLeast: 1, within: 3 } }] },
  { name: 'Uptrend', description: 'Price > SMA50 on 8 of last 10 bars, SMA50 > SMA200', conditions: [
    { left: 'price', op: '>', right: { kind: 'metric', metric: 'sma50' }, flex: { atLeast: 8, within: 10 } },
    { left: 'sma50', op: '>', right: { kind: 'metric', metric: 'sma200' } },
  ] },
  { name: 'Volume Surge', description: 'Volume 1.5x the 20-day average', conditions: [{ left: 'volumeRatio', op: '>', right: { kind: 'value', value: 1.5 } }] },
];

export const withIds = (cs: Omit<Condition, 'id'>[]): Condition[] => cs.map((c) => ({ ...c, id: cid() }));
export const newConditionId = cid;
