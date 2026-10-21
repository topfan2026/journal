import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Drawing, OptionLeg, Order } from '../lib/types';
import { newAccount, orderId, processPrice, type Account } from '../lib/paper';
import type { Condition } from '../lib/scanner';
import type { Timeframe } from '../lib/timeframes';

export type IndicatorKey = 'sma20' | 'sma50' | 'sma200' | 'ema9' | 'ema21' | 'bbands' | 'volume' | 'rsi' | 'macd' | 'stoch';
export type DrawTool = 'cursor' | 'trend' | 'channel' | 'measure' | 'hline';
export type ChartType = 'candles' | 'bars' | 'line';
export type PageId = 'basic' | 'trading' | 'scan' | 'chart1' | 'tf4' | 'options' | 'fundamentals';
export type TradingMode = 'paper' | 'live';
export type FlagColor = 'red' | 'yellow' | 'green' | 'blue' | 'purple';
export const FLAG_COLORS: FlagColor[] = ['red', 'yellow', 'green', 'blue', 'purple'];

export interface Note { text: string; updatedAt: number; x: number; y: number; visible: boolean }
export interface Alert { id: string; symbol: string; price: number; dir: 'above' | 'below'; createdAt: number; triggeredAt?: number }
export interface Toast { id: number; text: string; tone: 'up' | 'down' | 'info' }

interface WorkspaceState {
  page: PageId;
  symbol: string;
  tf: Timeframe;
  watchlist: string;
  customWatchlist: string[];
  flags: Record<string, FlagColor>;
  chartType: ChartType;
  logScale: boolean;
  indicators: Record<IndicatorKey, boolean>;
  tool: DrawTool;
  drawings: Record<string, Drawing[]>;
  notes: Record<string, Note>;
  splits: Record<string, number>;
  mode: TradingMode;
  paper: Account;
  alerts: Alert[];
  scanConditions: Condition[];
  savedScans: { name: string; conditions: Condition[] }[];
  strategy: { symbol: string; dte: number; legs: OptionLeg[]; showOnChart: boolean };
  toasts: Toast[];

  setSymbol: (s: string) => void;
  set: <K extends keyof WorkspaceState>(k: K, v: WorkspaceState[K]) => void;
  toggleIndicator: (k: IndicatorKey) => void;
  cycleFlag: (symbol: string) => void;
  toggleFavorite: (symbol: string) => void;
  addDrawing: (symbol: string, d: Drawing) => void;
  clearDrawings: (symbol: string) => void;
  saveNote: (symbol: string, patch: Partial<Note>) => void;
  placeOrders: (orders: Order[]) => void;
  modifyOrderPrice: (id: string, price: number) => void;
  cancelOrder: (id: string) => void;
  onPrice: (symbol: string, price: number) => void;
  addAlert: (symbol: string, price: number, last: number) => void;
  removeAlert: (id: string) => void;
  checkAlerts: (prices: Record<string, number>) => void;
  resetPaper: () => void;
  toast: (text: string, tone?: Toast['tone']) => void;
}

let toastSeq = 0;

function notify(title: string, body: string) {
  try {
    if (typeof Notification === 'undefined') return;
    if (Notification.permission === 'granted') new Notification(title, { body });
    else if (Notification.permission !== 'denied') Notification.requestPermission();
  } catch { /* notifications are optional */ }
}

export const useWorkspace = create<WorkspaceState>()(
  persist(
    (set, get) => ({
      page: 'basic',
      symbol: 'DIS',
      tf: 'D',
      watchlist: 'High Cap',
      customWatchlist: ['AAPL', 'NVDA', 'DIS'],
      flags: {},
      chartType: 'candles',
      logScale: false,
      indicators: { sma20: false, sma50: true, sma200: false, ema9: false, ema21: false, bbands: false, volume: true, rsi: false, macd: false, stoch: false },
      tool: 'cursor',
      drawings: {},
      notes: {},
      splits: {},
      mode: 'paper',
      paper: newAccount(),
      alerts: [],
      scanConditions: [],
      savedScans: [],
      strategy: { symbol: 'DIS', dte: 30, legs: [], showOnChart: true },
      toasts: [],

      setSymbol: (symbol) => set({ symbol }),
      set: (k, v) => set({ [k]: v } as Partial<WorkspaceState>),
      toggleIndicator: (k) => set((s) => ({ indicators: { ...s.indicators, [k]: !s.indicators[k] } })),
      cycleFlag: (symbol) => set((s) => {
        const cur = s.flags[symbol];
        const next = cur ? FLAG_COLORS[FLAG_COLORS.indexOf(cur) + 1] : FLAG_COLORS[0];
        const flags = { ...s.flags };
        if (next) flags[symbol] = next; else delete flags[symbol];
        return { flags };
      }),
      toggleFavorite: (symbol) => {
        const { customWatchlist: fav } = get();
        const has = fav.includes(symbol);
        set({ customWatchlist: has ? fav.filter((x) => x !== symbol) : [...fav, symbol] });
        get().toast(has ? `${symbol} removed from My Favorites` : `${symbol} added to My Favorites`);
      },
      addDrawing: (symbol, d) => set((s) => ({ drawings: { ...s.drawings, [symbol]: [...(s.drawings[symbol] ?? []), d] } })),
      clearDrawings: (symbol) => set((s) => ({ drawings: { ...s.drawings, [symbol]: [] } })),
      saveNote: (symbol, patch) => set((s) => {
        const prev = s.notes[symbol] ?? { text: '', updatedAt: 0, x: 24, y: 24, visible: false };
        return { notes: { ...s.notes, [symbol]: { ...prev, ...patch, updatedAt: Date.now() } } };
      }),
      placeOrders: (orders) => set((s) => ({ paper: { ...s.paper, orders: [...s.paper.orders, ...orders] } })),
      modifyOrderPrice: (id, price) => set((s) => ({ paper: { ...s.paper, orders: s.paper.orders.map((o) => (o.id === id ? { ...o, price: Math.round(price * 100) / 100 } : o)) } })),
      cancelOrder: (id) => set((s) => ({
        paper: { ...s.paper, orders: s.paper.orders.map((o) => (o.id === id || o.parentId === id) && o.status === 'WORKING' ? { ...o, status: 'CANCELLED' } : o) },
      })),
      onPrice: (symbol, price) => {
        const { paper } = get();
        if (!paper.orders.some((o) => o.symbol === symbol && o.status === 'WORKING')) return;
        const { account, fills } = processPrice(paper, symbol, price);
        set({ paper: account });
        fills.forEach((f) => get().toast(`${f.label ?? f.type} filled: ${f.side} ${f.qty} ${f.symbol} @ ${f.fillPrice?.toFixed(2)}`, f.side === 'BUY' ? 'up' : 'down'));
      },
      addAlert: (symbol, price, last) => {
        const a: Alert = { id: orderId(), symbol, price: Math.round(price * 100) / 100, dir: price >= last ? 'above' : 'below', createdAt: Date.now() };
        set((s) => ({ alerts: [...s.alerts, a] }));
        get().toast(`Alert set: ${symbol} ${a.dir === 'above' ? 'rises to' : 'falls to'} ${a.price.toFixed(2)}`);
      },
      removeAlert: (id) => set((s) => ({ alerts: s.alerts.filter((a) => a.id !== id) })),
      checkAlerts: (prices) => {
        const hit = get().alerts.filter((a) => !a.triggeredAt && prices[a.symbol] !== undefined && (a.dir === 'above' ? prices[a.symbol] >= a.price : prices[a.symbol] <= a.price));
        if (!hit.length) return;
        const now = Date.now();
        set((s) => ({ alerts: s.alerts.map((a) => (hit.some((h) => h.id === a.id) ? { ...a, triggeredAt: now } : a)) }));
        hit.forEach((a) => {
          const msg = `${a.symbol} ${a.dir === 'above' ? 'crossed above' : 'crossed below'} ${a.price.toFixed(2)} (last ${prices[a.symbol].toFixed(2)})`;
          get().toast(`🔔 ${msg}`, a.dir === 'above' ? 'up' : 'down');
          notify('ChartDesk alert', msg);
        });
      },
      resetPaper: () => set({ paper: newAccount() }),
      toast: (text, tone = 'info') => {
        const id = ++toastSeq;
        set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, tone }] }));
        setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 4000);
      },
    }),
    {
      name: 'chartdesk-workspace',
      version: 2,
      partialize: ({ toasts: _t, tool: _tool, ...rest }) => rest,
      // v1 stored a different layout model; keep the user's data, reset layout bits
      migrate: (persisted, version) => {
        const p = (persisted ?? {}) as Record<string, unknown>;
        if (version < 2) { delete p.layout; delete p.sizes; delete p.quadSymbols; }
        return p as unknown as WorkspaceState;
      },
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<WorkspaceState>;
        return { ...current, ...p, indicators: { ...current.indicators, ...(p.indicators ?? {}) } };
      },
    },
  ),
);
