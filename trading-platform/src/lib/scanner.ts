import type { Bar, SymbolInfo } from './types';
import { closes, macd, rsi, sma, type Series } from './indicators';

export type Metric =
  | 'price' | 'changePct' | 'rsi14' | 'macdLine' | 'macdSignal' | 'macdHist'
  | 'sma20' | 'sma50' | 'sma200' | 'volumeRatio' | 'epsGrowth' | 'marketCapB';

export const METRIC_LABELS: Record<Metric, string> = {
  price: 'Price', changePct: '% Change', rsi14: 'RSI(14)', macdLine: 'MACD', macdSignal: 'MACD Signal',
  macdHist: 'MACD Histogram', sma20: 'SMA 20', sma50: 'SMA 50', sma200: 'SMA 200',
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

type MetricSeries = Record<Metric, Series>;

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
  const last = s.price.length - 1;
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
