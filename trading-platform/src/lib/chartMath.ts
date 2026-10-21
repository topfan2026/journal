import type { Bar } from './types';

/** Map a unix time to a (possibly fractional / out-of-range) logical bar index. */
export function timeToLogical(bars: Bar[], t: number): number {
  if (!bars.length) return 0;
  const last = bars.length - 1;
  if (t >= bars[last].time) return last + (t - bars[last].time) / barSpacing(bars);
  if (t <= bars[0].time) return (t - bars[0].time) / barSpacing(bars);
  let lo = 0, hi = last;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (bars[mid].time <= t) lo = mid; else hi = mid;
  }
  return lo + (t - bars[lo].time) / Math.max(1, bars[hi].time - bars[lo].time);
}

export function logicalToTime(bars: Bar[], logical: number): number {
  if (!bars.length) return 0;
  const last = bars.length - 1;
  if (logical >= last) return Math.round(bars[last].time + (logical - last) * barSpacing(bars));
  if (logical <= 0) return Math.round(bars[0].time + logical * barSpacing(bars));
  const i = Math.floor(logical);
  return Math.round(bars[i].time + (logical - i) * (bars[i + 1].time - bars[i].time));
}

/** Median spacing in seconds between the last few bars — robust to weekends. */
function barSpacing(bars: Bar[]): number {
  const n = Math.min(bars.length - 1, 20);
  if (n < 1) return 86400;
  return (bars[bars.length - 1].time - bars[bars.length - 1 - n].time) / n;
}
