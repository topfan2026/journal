import { describe, expect, it } from 'vitest';
import { backtest, grid, walkForward, type StrategyDef } from '../src/lib/backtest';
import { computeSeries } from '../src/lib/scanner';
import { infoFor } from '../src/data/universe';
import { generateDailyBars } from '../src/data/mockMarket';
import type { Bar } from '../src/lib/types';

const mk = (rows: [number, number, number, number][]): Bar[] =>
  rows.map(([o, h, l, c], i) => ({ time: i * 86400, open: o, high: h, low: l, close: c, volume: 1000 }));

const def = (over: Partial<StrategyDef> = {}): StrategyDef => ({
  id: 't', name: 't', direction: 'long',
  entry: [{ id: 'e', left: 'price', op: '>', right: { kind: 'value', value: 100 } }],
  exit: [], sizing: { mode: 'shares', value: 10 }, commission: 0, slippagePct: 0, capital: 10_000, ...over,
});

describe('backtest engine', () => {
  it('enters at the next open and exits on target intrabar at the target price', () => {
    const bars = mk([[99, 101, 98, 101], [102, 103, 101, 102], [102, 111, 101, 109], [109, 110, 108, 109]]);
    const r = backtest(bars, computeSeries(bars, infoFor('X')), def({ targetPct: 5 }));
    expect(r.trades[0]).toMatchObject({ entryIdx: 1, entryPrice: 102, exitIdx: 2, reason: 'target' });
    expect(r.trades[0].exitPrice).toBeCloseTo(107.1);
    expect(r.trades[0].pnl).toBeCloseTo(51);
  });

  it('fills a gap-down through the stop at the open, not the stop price', () => {
    const bars = mk([[99, 101, 98, 101], [100, 101, 99, 100], [90, 92, 88, 91]]);
    const r = backtest(bars, computeSeries(bars, infoFor('X')), def({ stopPct: 5, entry: [{ id: 'e', left: 'price', op: '>', right: { kind: 'value', value: 100.5 } }] }));
    expect(r.trades[0]).toMatchObject({ reason: 'stop', exitPrice: 90 });
    expect(r.stats.netProfit).toBeCloseTo(-100);
  });

  it('assumes the stop is hit first when stop and target are inside the same bar', () => {
    const bars = mk([[99, 101, 98, 101], [100, 100, 100, 100], [100, 120, 80, 100]]);
    const r = backtest(bars, computeSeries(bars, infoFor('X')), def({ stopPct: 5, targetPct: 5 }));
    expect(r.trades[0].reason).toBe('stop');
  });

  it('trails a stop behind the highest high for longs and handles shorts symmetrically', () => {
    const bars = mk([[99, 101, 98, 101], [100, 100, 100, 100], [100, 110, 100, 110], [110, 110, 104, 105]]);
    const r = backtest(bars, computeSeries(bars, infoFor('X')), def({ trailPct: 5 }));
    expect(r.trades[0]).toMatchObject({ reason: 'trail' });
    expect(r.trades[0].exitPrice).toBeCloseTo(104.5);

    const down = mk([[101, 102, 99, 99], [100, 100, 100, 100], [100, 100, 90, 92], [92, 92, 90, 91]]);
    const s = backtest(down, computeSeries(down, infoFor('X')), def({ direction: 'short', entry: [{ id: 'e', left: 'price', op: '<', right: { kind: 'value', value: 100 } }] }));
    expect(s.trades[0]).toMatchObject({ side: 'short', entryPrice: 100, reason: 'end', exitPrice: 91 });
    expect(s.stats.netProfit).toBeCloseTo(90);
  });

  it('charges commission and slippage', () => {
    const bars = mk([[99, 101, 98, 101], [100, 100, 100, 100], [100, 100, 100, 100]]);
    const r = backtest(bars, computeSeries(bars, infoFor('X')), def({ commission: 1, slippagePct: 1 }));
    // buy 10 @101, sell 10 @99 at the end, $10 commission each side
    expect(r.stats.netProfit).toBeCloseTo(-20 - 20);
  });

  it('builds a parameter grid and walk-forward folds that do not overlap', () => {
    expect(grid([{ key: 'stopPct', from: 1, to: 3, step: 1 }, { key: 'targetPct', from: 5, to: 10, step: 5 }])).toHaveLength(6);
    const bars = generateDailyBars('AAPL');
    const series = computeSeries(bars, infoFor('AAPL'));
    const wf = walkForward(bars, series, def({ sizing: { mode: 'percent', value: 100 }, entry: [{ id: 'e', left: 'rsi14', op: 'crossesAbove', right: { kind: 'value', value: 30 } }], maxBars: 10 }),
      [{ key: 'stopPct', from: 2, to: 6, step: 2 }], { folds: 4, inSamplePct: 70, metric: 'netProfit' });
    expect(wf.folds).toHaveLength(4);
    wf.folds.forEach((f, i) => {
      expect(f.oosFrom).toBe(f.isTo + 1);
      if (i) expect(f.oosFrom).toBe(wf.folds[i - 1].oosTo + 1);
    });
    expect(wf.oosEquity.length).toBe(wf.folds.reduce((a, f) => a + f.oosTo - f.oosFrom + 1, 0));
  });
});
