import { create } from 'zustand';
import type { Bar } from '../lib/types';
import { generateDailyBars, nextTick } from '../data/mockMarket';
import { infoFor, UNIVERSE } from '../data/universe';
import { ibkr, type IbkrStatus } from '../lib/ibkr';

export type DataSource = 'mock' | 'ibkr';

interface MarketState {
  source: DataSource;
  ibkr: IbkrStatus | null;
  bars: Record<string, Bar[]>;
  prevClose: Record<string, number>;
  loading: Record<string, boolean>;
  setSource: (s: DataSource) => void;
  checkIbkr: () => Promise<IbkrStatus>;
  ensure: (symbol: string) => void;
  mockTick: () => void;
  applyQuote: (symbol: string, last: number, volume?: number | null) => void;
}

function loadMock(symbol: string) {
  const bars = generateDailyBars(symbol);
  return { bars, prev: bars[bars.length - 2]?.close ?? bars[bars.length - 1].close };
}

const initial = UNIVERSE.map((s) => [s.symbol, loadMock(s.symbol)] as const);

export const useMarket = create<MarketState>((set, get) => ({
  source: 'mock',
  ibkr: null,
  bars: Object.fromEntries(initial.map(([s, m]) => [s, m.bars])),
  prevClose: Object.fromEntries(initial.map(([s, m]) => [s, m.prev])),
  loading: {},

  setSource: (source) => {
    set({ source });
    if (source === 'mock') {
      const fresh = Object.keys(get().bars).map((s) => [s, loadMock(s)] as const);
      set({ bars: Object.fromEntries(fresh.map(([s, m]) => [s, m.bars])), prevClose: Object.fromEntries(fresh.map(([s, m]) => [s, m.prev])) });
    } else {
      // reload history from IBKR for everything currently loaded
      const symbols = Object.keys(get().bars);
      set({ bars: {}, prevClose: {} });
      symbols.forEach((s) => get().ensure(s));
    }
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
    if (source === 'mock') {
      const m = loadMock(symbol);
      set((s) => ({ bars: { ...s.bars, [symbol]: m.bars }, prevClose: { ...s.prevClose, [symbol]: m.prev } }));
      return;
    }
    set((s) => ({ loading: { ...s.loading, [symbol]: true } }));
    ibkr.history(symbol)
      .then((h) => {
        if (!h.length) throw new Error('no history');
        set((s) => ({ bars: { ...s.bars, [symbol]: h }, prevClose: { ...s.prevClose, [symbol]: h[h.length - 2]?.close ?? h[h.length - 1].close } }));
      })
      .catch(() => {
        // fall back to simulated data so the UI stays usable for symbols IBKR can't serve
        const m = loadMock(symbol);
        set((s) => ({ bars: { ...s.bars, [symbol]: m.bars }, prevClose: { ...s.prevClose, [symbol]: m.prev } }));
      })
      .finally(() => set((s) => ({ loading: { ...s.loading, [symbol]: false } })));
  },

  mockTick: () => {
    set((s) => {
      const bars: Record<string, Bar[]> = {};
      for (const [sym, arr] of Object.entries(s.bars)) {
        const last = arr[arr.length - 1];
        bars[sym] = [...arr.slice(0, -1), nextTick(last, infoFor(sym).vol)];
      }
      return { bars };
    });
  },

  applyQuote: (symbol, last, volume) => {
    set((s) => {
      const arr = s.bars[symbol];
      if (!arr?.length) return s;
      const b = arr[arr.length - 1];
      const nb = { ...b, close: last, high: Math.max(b.high, last), low: Math.min(b.low, last), volume: volume ?? b.volume };
      return { bars: { ...s.bars, [symbol]: [...arr.slice(0, -1), nb] } };
    });
  },
}));

export const lastPrice = (bars: Bar[] | undefined) => (bars?.length ? bars[bars.length - 1].close : 0);
