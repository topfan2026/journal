export type Timeframe = '1m' | '5m' | '15m' | '1h' | 'D' | 'W';

export const TIMEFRAMES: Timeframe[] = ['1m', '5m', '15m', '1h', 'D', 'W'];

export const TF_LABEL: Record<Timeframe, string> = { '1m': '1 Minute', '5m': '5 Minute', '15m': '15 Minute', '1h': '60 Minute', D: 'Daily', W: 'Weekly' };

/** Seconds per bar for intraday frames; sessions are 6.5h (390 min). */
export const TF_SECONDS: Record<Timeframe, number> = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600, D: 86400, W: 604800 };

/** IBKR Client Portal history parameters per timeframe. */
export const IBKR_PARAMS: Record<Timeframe, { period: string; bar: string }> = {
  '1m': { period: '2d', bar: '1min' },
  '5m': { period: '1w', bar: '5min' },
  '15m': { period: '1m', bar: '15min' },
  '1h': { period: '6m', bar: '1h' },
  D: { period: '5y', bar: '1d' },
  W: { period: '5y', bar: '1w' },
};

export const isIntraday = (tf: Timeframe) => tf !== 'D' && tf !== 'W';
