import type { StrategyDef } from '../lib/backtest';
import type { Condition } from '../lib/scanner';

let n = 0;
const id = () => `s${Date.now().toString(36)}${n++}`;
const c = (x: Omit<Condition, 'id'>): Condition => ({ ...x, id: id() });

const base = { sizing: { mode: 'percent' as const, value: 100 }, commission: 0.005, slippagePct: 0.02, capital: 100_000 };

/** Starter strategies. Each call returns fresh ids so templates can be edited independently. */
export const TEMPLATES: { name: string; description: string; make: () => Omit<StrategyDef, 'id'> }[] = [
  {
    name: 'SMA 20/50 crossover',
    description: 'Buy when SMA 20 crosses above SMA 50, sell when it crosses back below.',
    make: () => ({ ...base, name: 'SMA 20/50 crossover', direction: 'long',
      entry: [c({ left: 'sma20', op: 'crossesAbove', right: { kind: 'metric', metric: 'sma50' } })],
      exit: [c({ left: 'sma20', op: 'crossesBelow', right: { kind: 'metric', metric: 'sma50' } })],
      stopPct: 8 }),
  },
  {
    name: 'RSI mean reversion',
    description: 'Buy when RSI(14) crosses up through 30 in an uptrend; exit when RSI > 60 or after 10 bars.',
    make: () => ({ ...base, name: 'RSI mean reversion', direction: 'long',
      entry: [
        c({ left: 'rsi14', op: 'crossesAbove', right: { kind: 'value', value: 30 } }),
        c({ left: 'price', op: '>', right: { kind: 'metric', metric: 'sma200' } }),
      ],
      exit: [c({ left: 'rsi14', op: '>', right: { kind: 'value', value: 60 } })],
      stopPct: 5, maxBars: 10 }),
  },
  {
    name: '20-bar breakout',
    description: 'Buy a close above the prior 20-bar high with volume 1.5x average; 3% trailing stop.',
    make: () => ({ ...base, name: '20-bar breakout', direction: 'long',
      entry: [
        c({ left: 'price', op: '>', right: { kind: 'metric', metric: 'high20' } }),
        c({ left: 'volumeRatio', op: '>', right: { kind: 'value', value: 1.5 } }),
      ],
      exit: [], stopPct: 4, trailPct: 3 }),
  },
  {
    name: 'MACD trend',
    description: 'Buy when MACD crosses above its signal while price is above SMA 50.',
    make: () => ({ ...base, name: 'MACD trend', direction: 'long',
      entry: [
        c({ left: 'macdLine', op: 'crossesAbove', right: { kind: 'metric', metric: 'macdSignal' } }),
        c({ left: 'price', op: '>', right: { kind: 'metric', metric: 'sma50' } }),
      ],
      exit: [c({ left: 'macdLine', op: 'crossesBelow', right: { kind: 'metric', metric: 'macdSignal' } })],
      stopPct: 6, targetPct: 15 }),
  },
  {
    name: 'EMA 9/21 short',
    description: 'Short when EMA 9 crosses below EMA 21 under SMA 200; cover on the opposite cross.',
    make: () => ({ ...base, name: 'EMA 9/21 short', direction: 'short',
      entry: [
        c({ left: 'ema9', op: 'crossesBelow', right: { kind: 'metric', metric: 'ema21' } }),
        c({ left: 'price', op: '<', right: { kind: 'metric', metric: 'sma200' } }),
      ],
      exit: [c({ left: 'ema9', op: 'crossesAbove', right: { kind: 'metric', metric: 'ema21' } })],
      stopPct: 5 }),
  },
];

export const newStrategy = (t = TEMPLATES[0]): StrategyDef => ({ ...t.make(), id: id() });
