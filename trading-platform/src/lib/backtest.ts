import type { Bar } from './types';
import { evaluateAt, type Condition, type MetricSeries } from './scanner';

export interface StrategyDef {
  id: string;
  name: string;
  direction: 'long' | 'short';
  /** All entry conditions must be true at a bar's close; the trade opens at the next bar's open. */
  entry: Condition[];
  /** Any exit condition true at a bar's close closes the trade at the next bar's open. */
  exit: Condition[];
  stopPct?: number;
  targetPct?: number;
  trailPct?: number;
  maxBars?: number;
  sizing: { mode: 'percent' | 'shares'; value: number };
  commission: number; // $ per share, each side
  slippagePct: number; // % of price, each side
  capital: number;
}

export type ExitReason = 'stop' | 'target' | 'trail' | 'signal' | 'time' | 'end';

export interface Trade {
  side: 'long' | 'short';
  entryIdx: number;
  exitIdx: number;
  entryTime: number;
  exitTime: number;
  entryPrice: number;
  exitPrice: number;
  qty: number;
  pnl: number; // after costs
  pnlPct: number; // on entry notional
  bars: number;
  reason: ExitReason;
}

export interface Stats {
  netProfit: number;
  netPct: number;
  trades: number;
  winRate: number;
  profitFactor: number; // Infinity when there are no losses
  avgTrade: number;
  avgWinPct: number;
  avgLossPct: number;
  maxDrawdownPct: number;
  sharpe: number;
  exposurePct: number;
  buyHoldPct: number;
  endEquity: number;
}

export interface EquityPoint { time: number; value: number }
export interface BacktestResult { trades: Trade[]; equity: EquityPoint[]; stats: Stats }

export interface RunOptions {
  from?: number;
  to?: number;
  /** Bars per year, for annualizing Sharpe (252 daily, 52 weekly, …). */
  periodsPerYear?: number;
  /** Starting equity override (walk-forward chains folds). */
  capital?: number;
}

export function backtest(bars: Bar[], series: MetricSeries, def: StrategyDef, opts: RunOptions = {}): BacktestResult {
  const from = Math.max(0, opts.from ?? 0);
  const to = Math.min(bars.length - 1, opts.to ?? bars.length - 1);
  const capital = opts.capital ?? def.capital;
  const long = def.direction === 'long';
  const dir = long ? 1 : -1;
  const slip = def.slippagePct / 100;

  let cash = capital;
  let qty = 0; // shares held (always positive; direction from def)
  let entryPrice = 0, entryIdx = -1, entryCost = 0;
  let stop: number | null = null, target: number | null = null, anchor = 0;
  let pendingEntry = false, pendingExit = false;
  let barsInMarket = 0;
  const trades: Trade[] = [];
  const equity: EquityPoint[] = [];

  const fill = (px: number, buying: boolean) => px * (buying ? 1 + slip : 1 - slip);
  const mark = (px: number) => cash + dir * qty * px;

  const open = (i: number) => {
    const px = fill(bars[i].open, long);
    const eq = cash;
    const n = def.sizing.mode === 'shares' ? def.sizing.value : Math.floor((eq * def.sizing.value) / 100 / px);
    if (n < 1) return;
    qty = n;
    entryPrice = px;
    entryIdx = i;
    entryCost = n * def.commission;
    cash -= dir * n * px + entryCost;
    stop = def.stopPct ? px * (1 - (dir * def.stopPct) / 100) : null;
    target = def.targetPct ? px * (1 + (dir * def.targetPct) / 100) : null;
    anchor = px;
  };

  const close = (i: number, px: number, reason: ExitReason, slipped = true) => {
    const exitPx = slipped ? fill(px, !long) : px;
    const cost = qty * def.commission;
    cash += dir * qty * exitPx - cost;
    const gross = dir * qty * (exitPx - entryPrice);
    const pnl = gross - entryCost - cost;
    trades.push({
      side: def.direction, entryIdx, exitIdx: i, entryTime: bars[entryIdx].time, exitTime: bars[i].time,
      entryPrice, exitPrice: exitPx, qty, pnl, pnlPct: (pnl / (qty * entryPrice)) * 100, bars: i - entryIdx + 1, reason,
    });
    qty = 0;
    stop = target = null;
  };

  for (let i = from; i <= to; i++) {
    const b = bars[i];
    if (pendingExit && qty) close(i, b.open, 'signal');
    if (pendingEntry && !qty) open(i);
    pendingEntry = pendingExit = false;

    if (qty) {
      barsInMarket++;
      const trailStop = def.trailPct ? anchor * (1 - (dir * def.trailPct) / 100) : null;
      // effective protective stop is the tighter of fixed and trailing
      const prot = [stop, trailStop].filter((x): x is number => x !== null);
      const eff = prot.length ? (long ? Math.max(...prot) : Math.min(...prot)) : null;
      const reasonFor = (lvl: number) => (trailStop !== null && lvl === trailStop && lvl !== stop ? 'trail' : 'stop');
      if (eff !== null && (long ? b.open <= eff : b.open >= eff)) close(i, b.open, reasonFor(eff));
      else if (eff !== null && (long ? b.low <= eff : b.high >= eff)) close(i, eff, reasonFor(eff));
      else if (target !== null && (long ? b.open >= target : b.open <= target)) close(i, b.open, 'target');
      else if (target !== null && (long ? b.high >= target : b.low <= target)) close(i, target, 'target', false);
      if (qty) anchor = long ? Math.max(anchor, b.high) : Math.min(anchor, b.low);
      if (qty && def.maxBars && i - entryIdx + 1 >= def.maxBars) close(i, b.close, 'time');
      if (qty && i < to && def.exit.length && def.exit.some((c) => evaluateAt(series, c, i))) pendingExit = true;
    }
    if (!qty && i < to && def.entry.length && def.entry.every((c) => evaluateAt(series, c, i))) pendingEntry = true;
    if (qty && i === to) close(i, b.close, 'end');
    equity.push({ time: b.time, value: mark(b.close) });
  }

  return { trades, equity, stats: computeStats(trades, equity, capital, bars, from, to, barsInMarket, opts.periodsPerYear ?? 252) };
}

export function computeStats(trades: Trade[], equity: EquityPoint[], capital: number, bars: Bar[], from: number, to: number, barsInMarket: number, ppy: number): Stats {
  const end = equity.length ? equity[equity.length - 1].value : capital;
  const wins = trades.filter((t) => t.pnl > 0), losses = trades.filter((t) => t.pnl <= 0);
  const grossWin = wins.reduce((a, t) => a + t.pnl, 0), grossLoss = -losses.reduce((a, t) => a + t.pnl, 0);
  let peak = capital, maxDd = 0;
  for (const p of equity) { peak = Math.max(peak, p.value); maxDd = Math.max(maxDd, (peak - p.value) / peak); }
  const rets = equity.slice(1).map((p, i) => p.value / equity[i].value - 1);
  const mean = rets.reduce((a, r) => a + r, 0) / Math.max(1, rets.length);
  const sd = Math.sqrt(rets.reduce((a, r) => a + (r - mean) ** 2, 0) / Math.max(1, rets.length));
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
  return {
    netProfit: end - capital,
    netPct: ((end - capital) / capital) * 100,
    trades: trades.length,
    winRate: trades.length ? (wins.length / trades.length) * 100 : 0,
    profitFactor: grossLoss === 0 ? (grossWin > 0 ? Infinity : 0) : grossWin / grossLoss,
    avgTrade: trades.length ? (grossWin - grossLoss) / trades.length : 0,
    avgWinPct: avg(wins.map((t) => t.pnlPct)),
    avgLossPct: avg(losses.map((t) => t.pnlPct)),
    maxDrawdownPct: maxDd * 100,
    sharpe: sd > 0 ? (mean / sd) * Math.sqrt(ppy) : 0,
    exposurePct: (barsInMarket / Math.max(1, to - from + 1)) * 100,
    buyHoldPct: bars[to] && bars[from] ? ((bars[to].close - bars[from].open) / bars[from].open) * 100 : 0,
    endEquity: end,
  };
}

// ---- optimization & walk-forward -----------------------------------------------------------

export type ParamKey = 'stopPct' | 'targetPct' | 'trailPct' | 'maxBars' | 'entryValue';
export const PARAM_LABELS: Record<ParamKey, string> = {
  stopPct: 'Stop loss %', targetPct: 'Profit target %', trailPct: 'Trailing stop %', maxBars: 'Max bars held', entryValue: 'Entry rule #1 value',
};
export interface ParamRange { key: ParamKey; from: number; to: number; step: number }
export type ParamValues = Partial<Record<ParamKey, number>>;
export type OptimizeMetric = 'netProfit' | 'sharpe' | 'profitFactor';

export function applyParams(def: StrategyDef, v: ParamValues): StrategyDef {
  const out: StrategyDef = { ...def };
  if (v.stopPct !== undefined) out.stopPct = v.stopPct;
  if (v.targetPct !== undefined) out.targetPct = v.targetPct;
  if (v.trailPct !== undefined) out.trailPct = v.trailPct;
  if (v.maxBars !== undefined) out.maxBars = v.maxBars;
  if (v.entryValue !== undefined && def.entry[0]?.right.kind === 'value') {
    out.entry = [{ ...def.entry[0], right: { kind: 'value', value: v.entryValue } }, ...def.entry.slice(1)];
  }
  return out;
}

function steps(r: ParamRange): number[] {
  const out: number[] = [];
  const step = Math.abs(r.step) || 1;
  for (let x = r.from; x <= r.to + 1e-9 && out.length < 50; x += step) out.push(Math.round(x * 1e6) / 1e6);
  return out;
}

export function grid(ranges: ParamRange[]): ParamValues[] {
  return ranges.reduce<ParamValues[]>((acc, r) => acc.flatMap((v) => steps(r).map((x) => ({ ...v, [r.key]: x }))), [{}]);
}

const score = (s: Stats, m: OptimizeMetric) => {
  if (s.trades < 3) return -Infinity; // too few trades to trust
  return m === 'profitFactor' ? Math.min(s.profitFactor, 100) : s[m];
};

export function optimize(bars: Bar[], series: MetricSeries, def: StrategyDef, ranges: ParamRange[], metric: OptimizeMetric, opts: RunOptions = {}) {
  const results = grid(ranges).map((values) => ({ values, stats: backtest(bars, series, applyParams(def, values), opts).stats }));
  results.sort((a, b) => score(b.stats, metric) - score(a.stats, metric));
  return { best: results[0]?.values ?? {}, results };
}

export interface Fold {
  isFrom: number; isTo: number; oosFrom: number; oosTo: number;
  params: ParamValues; is: Stats; oos: Stats;
}

/**
 * Rolling walk-forward: for each fold, optimize on the in-sample window, then trade the following
 * out-of-sample window with those parameters. OOS segments are chained into one equity curve.
 */
export function walkForward(
  bars: Bar[], series: MetricSeries, def: StrategyDef, ranges: ParamRange[],
  { folds, inSamplePct, metric, warmup = 50, periodsPerYear = 252 }: { folds: number; inSamplePct: number; metric: OptimizeMetric; warmup?: number; periodsPerYear?: number },
) {
  const start = Math.min(warmup, Math.floor(bars.length / 4));
  const n = bars.length - start;
  const oosLen = Math.max(5, Math.floor((n * (1 - inSamplePct / 100)) / folds));
  const isLen = n - folds * oosLen;
  const out: Fold[] = [];
  const oosTrades: Trade[] = [];
  const oosEquity: EquityPoint[] = [];
  let capital = def.capital;
  let barsInMarket = 0;
  if (isLen < 20) return { folds: out, oosTrades, oosEquity, oosStats: computeStats([], [], capital, bars, 0, 0, 0, periodsPerYear) };

  for (let k = 0; k < folds; k++) {
    const isFrom = start + k * oosLen, isTo = isFrom + isLen - 1;
    const oosFrom = isTo + 1, oosTo = Math.min(bars.length - 1, oosFrom + oosLen - 1);
    const { best } = optimize(bars, series, def, ranges, metric, { from: isFrom, to: isTo, periodsPerYear });
    const tuned = applyParams(def, best);
    const is = backtest(bars, series, tuned, { from: isFrom, to: isTo, periodsPerYear }).stats;
    const oos = backtest(bars, series, tuned, { from: oosFrom, to: oosTo, periodsPerYear, capital });
    out.push({ isFrom, isTo, oosFrom, oosTo, params: best, is, oos: oos.stats });
    oosTrades.push(...oos.trades);
    oosEquity.push(...oos.equity);
    barsInMarket += (oos.stats.exposurePct / 100) * (oosTo - oosFrom + 1);
    capital = oos.stats.endEquity;
  }
  const first = out[0]?.oosFrom ?? 0, last = out[out.length - 1]?.oosTo ?? 0;
  return { folds: out, oosTrades, oosEquity, oosStats: computeStats(oosTrades, oosEquity, def.capital, bars, first, last, barsInMarket, periodsPerYear) };
}
