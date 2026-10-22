import { create } from 'zustand';
import type { Bar } from '../lib/types';
import { generateBars, generateDailyBars, nextTick } from '../data/mockMarket';
import { infoFor, UNIVERSE } from '../data/universe';
import { ibkr, type IbkrStatus } from '../lib/ibkr';
import type { Timeframe } from '../lib/timeframes';

export type DataSource = 'mock' | 'ibkr';

interface MarketState {
  source: DataSource;
  ibkr: IbkrStatus | null;
  /** Daily bars per symbol — the reference series for quotes, scans and the paper engine. */
  bars: Record<string, Bar[]>;
  /** Non-daily bars keyed `${symbol}|${tf}`; their last bar tracks the daily last price. */
  tfBars: Record<string, Bar[]>;
  prevClose: Record<string, number>;
  /** Latest bid/ask from IBKR (simulated data derives a spread instead). */
  quotes: Record<string, { bid: number | null; ask: number | null }>;
  loading: Record<string, boolean>;
  setSource: (s: DataSource) => void;
  checkIbkr: () => Promise<IbkrStatus>;
  ensure: (symbol: string) => void;
  ensureTf: (symbol: string, tf: Timeframe) => void;
  mockTick: () => void;
  applyQuote: (symbol: string, last: number, volume?: number | null, bid?: number | null, ask?: number | null) => void;
}

export const tfKey = (symbol: string, tf: Timeframe) => `${symbol}|${tf}`;

function loadMock(symbol: string) {
  const bars = generateDailyBars(symbol);
  return { bars, prev: bars[bars.length - 2]?.close ?? bars[bars.length - 1].close };
}

/** Move the last bar of a series to `price`, widening its range as needed. */
function withLast(arr: Bar[], price: number, volAdd = 0): Bar[] {
  const b = arr[arr.length - 1];
  return [...arr.slice(0, -1), { ...b, close: price, high: Math.max(b.high, price), low: Math.min(b.low, price), volume: b.volume + volAdd }];
}

const initial = UNIVERSE.map((s) => [s.symbol, loadMock(s.symbol)] as const);

export const useMarket = create<MarketState>((set, get) => ({
  source: 'mock',
  ibkr: null,
  bars: Object.fromEntries(initial.map(([s, m]) => [s, m.bars])),
  tfBars: {},
  quotes: {},
  prevClose: Object.fromEntries(initial.map(([s, m]) => [s, m.prev])),
  loading: {},

  setSource: (source) => {
    const symbols = Object.keys(get().bars);
    const frames = Object.keys(get().tfBars);
    set({ source, tfBars: {} });
    if (source === 'mock') {
      const fresh = symbols.map((s) => [s, loadMock(s)] as const);
      set({ bars: Object.fromEntries(fresh.map(([s, m]) => [s, m.bars])), prevClose: Object.fromEntries(fresh.map(([s, m]) => [s, m.prev])) });
    } else {
      set({ bars: {}, prevClose: {} });
      symbols.forEach((s) => get().ensure(s));
    }
    frames.forEach((k) => { const [s, tf] = k.split('|'); get().ensureTf(s, tf as Timeframe); });
  },

  checkIbkr: async () => {
    let status: IbkrStatus;
    try { status = await ibkr.status(); } catch (e) { status = { reachable: false, authenticated: false, connected: false, message: String(e) }; }
    set({ ibkr: status });
    return status;
  },

  ensure: (symbol) => {
    const { bars, loading, source } = get();
    if (bars[symbol] || loading[symbol]) return;
    const useMock = () => {
      const m = loadMock(symbol);
      set((s) => ({ bars: { ...s.bars, [symbol]: m.bars }, prevClose: { ...s.prevClose, [symbol]: m.prev } }));
    };
    if (source === 'mock') return useMock();
    set((s) => ({ loading: { ...s.loading, [symbol]: true } }));
    ibkr.history(symbol, 'D')
      .then((h) => {
        if (!h.length) throw new Error('no history');
        set((s) => ({ bars: { ...s.bars, [symbol]: h }, prevClose: { ...s.prevClose, [symbol]: h[h.length - 2]?.close ?? h[h.length - 1].close } }));
      })
      // fall back to simulated data so the UI stays usable for symbols IBKR can't serve
      .catch(useMock)
      .finally(() => set((s) => ({ loading: { ...s.loading, [symbol]: false } })));
  },

  ensureTf: (symbol, tf) => {
    if (tf === 'D') return get().ensure(symbol);
    const key = tfKey(symbol, tf);
    const { tfBars, loading, source } = get();
    if (tfBars[key] || loading[key]) return;
    get().ensure(symbol);
    const useMock = () => {
      const daily = get().bars[symbol];
      const anchor = daily?.[daily.length - 1]?.close;
      set((s) => ({ tfBars: { ...s.tfBars, [key]: generateBars(symbol, tf, anchor) } }));
    };
    if (source === 'mock') return useMock();
    set((s) => ({ loading: { ...s.loading, [key]: true } }));
    ibkr.history(symbol, tf)
      .then((h) => {
        if (!h.length) throw new Error('no history');
        set((s) => ({ tfBars: { ...s.tfBars, [key]: h } }));
      })
      .catch(useMock)
      .finally(() => set((s) => ({ loading: { ...s.loading, [key]: false } })));
  },

  mockTick: () => {
    set((s) => {
      const bars: Record<string, Bar[]> = {};
      for (const [sym, arr] of Object.entries(s.bars)) {
        bars[sym] = [...arr.slice(0, -1), nextTick(arr[arr.length - 1], infoFor(sym).vol)];
      }
      const tfBars: Record<string, Bar[]> = {};
      for (const [key, arr] of Object.entries(s.tfBars)) {
        const d = bars[key.split('|')[0]];
        tfBars[key] = d ? withLast(arr, d[d.length - 1].close, Math.round(Math.random() * 3000)) : arr;
      }
      return { bars, tfBars };
    });
  },

  applyQuote: (symbol, last, volume, bid, ask) => {
    if (bid != null || ask != null) set((s) => ({ quotes: { ...s.quotes, [symbol]: { bid: bid ?? null, ask: ask ?? null } } }));
    set((s) => {
      const arr = s.bars[symbol];
      if (!arr?.length) return s;
      const daily = withLast(arr, last);
      if (volume != null) daily[daily.length - 1].volume = volume;
      const tfBars = { ...s.tfBars };
      for (const key of Object.keys(tfBars)) if (key.startsWith(`${symbol}|`)) tfBars[key] = withLast(tfBars[key], last);
      return { bars: { ...s.bars, [symbol]: daily }, tfBars };
    });
  },
}));

export const lastPrice = (bars: Bar[] | undefined) => (bars?.length ? bars[bars.length - 1].close : 0);

/** Select the series for a symbol at a timeframe. */
export const selectBars = (symbol: string, tf: Timeframe) => (s: MarketState) => (tf === 'D' ? s.bars[symbol] : s.tfBars[tfKey(symbol, tf)]);
