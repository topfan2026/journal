import { describe, expect, it } from 'vitest';
import { computeSeries, evaluate, type Condition } from '../src/lib/scanner';
import { rsi, sma } from '../src/lib/indicators';
import type { Bar } from '../src/lib/types';
import { infoFor } from '../src/data/universe';

const bars = (closes: number[]): Bar[] => closes.map((c, i) => ({ time: i * 86400, open: c, high: c, low: c, close: c, volume: 1000 }));

describe('indicators', () => {
  it('computes SMA', () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });
  it('RSI is 100 on a pure uptrend and 0 on a pure downtrend', () => {
    const up = Array.from({ length: 30 }, (_, i) => 100 + i);
    expect(rsi(up).at(-1)).toBe(100);
    expect(rsi(up.slice().reverse()).at(-1)).toBeCloseTo(0);
  });
});

describe('scanner conditions', () => {
  const info = infoFor('AAPL');
  it('detects a cross above a value only on the crossing bar, and Flex widens the window', () => {
    const s = computeSeries(bars([1, 1, 1, 5, 6, 7]), info);
    const cross: Condition = { id: 'a', left: 'price', op: 'crossesAbove', right: { kind: 'value', value: 3 } };
    expect(evaluate(s, cross)).toBe(false); // crossed 3 bars ago
    expect(evaluate(s, { ...cross, flex: { atLeast: 1, within: 3 } })).toBe(true);
  });
  it('requires N of M bars for flex conditions', () => {
    const s = computeSeries(bars([10, 1, 10, 10, 1, 10]), info);
    const above: Condition = { id: 'b', left: 'price', op: '>', right: { kind: 'value', value: 5 } };
    expect(evaluate(s, { ...above, flex: { atLeast: 4, within: 5 } })).toBe(false);
    expect(evaluate(s, { ...above, flex: { atLeast: 3, within: 5 } })).toBe(true);
  });
  it('compares fundamentals', () => {
    const s = computeSeries(bars([1, 2]), infoFor('NVDA'));
    expect(evaluate(s, { id: 'c', left: 'epsGrowth', op: '>', right: { kind: 'value', value: 25 } })).toBe(true);
  });
});
