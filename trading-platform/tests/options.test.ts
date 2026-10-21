import { describe, expect, it } from 'vitest';
import { analyze, blackScholes, buildChain, payoffAt } from '../src/lib/options';
import type { OptionLeg } from '../src/lib/types';

const leg = (right: 'C' | 'P', strike: number, qty: number, premium: number): OptionLeg => ({ id: `${right}${strike}${qty}`, right, strike, qty, premium });

describe('options math', () => {
  it('satisfies put-call parity', () => {
    const S = 100, K = 105, T = 0.25, r = 0.045, v = 0.3;
    const c = blackScholes('C', S, K, T, v, r).price;
    const p = blackScholes('P', S, K, T, v, r).price;
    expect(c - p).toBeCloseTo(S - K * Math.exp(-r * T), 2);
  });

  it('analyzes a bull call spread', () => {
    const legs = [leg('C', 100, 1, 5), leg('C', 110, -1, 2)];
    const s = analyze(legs, 50, 150);
    expect(s.netDebit).toBe(300);
    expect(s.maxLoss).toBeCloseTo(-300);
    expect(s.maxProfit).toBeCloseTo(700);
    expect(s.breakevens).toEqual([103]);
    expect(s.zones.map((z) => z.profit)).toEqual([false, true]);
  });

  it('flags unlimited profit on a long straddle and finds both breakevens', () => {
    const s = analyze([leg('C', 100, 1, 4), leg('P', 100, 1, 4)], 50, 150);
    expect(s.maxProfit).toBe(Infinity);
    expect(s.maxLoss).toBeCloseTo(-800);
    expect(s.breakevens).toEqual([92, 108]);
    expect(s.zones.map((z) => z.profit)).toEqual([true, false, true]);
  });

  it('bounds risk on an iron condor', () => {
    const legs = [leg('P', 90, 1, 0.5), leg('P', 95, -1, 1.5), leg('C', 105, -1, 1.5), leg('C', 110, 1, 0.5)];
    const s = analyze(legs, 50, 150);
    expect(s.maxProfit).toBeCloseTo(200);
    expect(s.maxLoss).toBeCloseTo(-300);
    expect(payoffAt(legs, 100)).toBeCloseTo(200);
    expect(s.breakevens).toEqual([93, 107]);
  });

  it('builds a chain with bid < ask around spot', () => {
    const ch = buildChain(150, 0.3, 30);
    expect(ch.strikes).toHaveLength(21);
    ch.calls.concat(ch.puts).forEach((q) => expect(q.bid).toBeLessThanOrEqual(q.ask));
  });
});
