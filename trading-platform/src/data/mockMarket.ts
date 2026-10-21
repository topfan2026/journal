import type { Bar } from '../lib/types';
import { gaussian, hashString, mulberry32 } from '../lib/random';
import { infoFor } from './universe';

const DAY = 86400;

/** Generate ~1 year of daily bars ending today with a seeded GBM + mild regime drift. */
export function generateDailyBars(symbol: string, count = 260, endTime = todayUtc()): Bar[] {
  const info = infoFor(symbol);
  const rand = mulberry32(hashString(symbol));
  const dailyVol = info.vol / Math.sqrt(252);
  const bars: Bar[] = [];
  // walk backward in calendar days, skipping weekends, then reverse
  const times: number[] = [];
  let t = endTime;
  while (times.length < count) {
    const dow = new Date(t * 1000).getUTCDay();
    if (dow !== 0 && dow !== 6) times.push(t);
    t -= DAY;
  }
  times.reverse();

  let price = info.basePrice * (0.75 + rand() * 0.3);
  let drift = 0;
  for (const time of times) {
    if (rand() < 0.03) drift = (rand() - 0.45) * dailyVol * 0.6; // occasional regime change
    const ret = drift + gaussian(rand) * dailyVol;
    const open = price * (1 + gaussian(rand) * dailyVol * 0.25);
    const close = open * Math.exp(ret);
    const range = Math.abs(gaussian(rand)) * dailyVol * price * 0.8;
    const high = Math.max(open, close) + range * rand();
    const low = Math.min(open, close) - range * rand();
    const volume = Math.round((5e6 + rand() * 4e7) * (1 + Math.abs(ret) / dailyVol) * (info.marketCapB / 500 + 0.3));
    bars.push({ time, open: r2(open), high: r2(high), low: r2(low), close: r2(close), volume });
    price = close;
  }
  // re-anchor so the last close sits near the reference price
  const scale = info.basePrice / bars[bars.length - 1].close;
  return bars.map((b) => ({ ...b, open: r2(b.open * scale), high: r2(b.high * scale), low: r2(b.low * scale), close: r2(b.close * scale) }));
}

/** Advance the last bar by one simulated tick; returns the new last bar. */
export function nextTick(last: Bar, vol: number, rand: () => number = Math.random): Bar {
  const tickVol = vol / Math.sqrt(252 * 390 * 6); // ~10s ticks
  const close = r2(last.close * Math.exp(gaussian(rand) * tickVol * 1.5));
  return {
    ...last,
    close,
    high: Math.max(last.high, close),
    low: Math.min(last.low, close),
    volume: last.volume + Math.round(rand() * 20000),
  };
}

export function todayUtc(): number {
  const d = new Date();
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) / 1000;
}

export const r2 = (n: number) => Math.round(n * 100) / 100;
