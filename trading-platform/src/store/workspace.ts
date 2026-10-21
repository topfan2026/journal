import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Drawing, OptionLeg, Order } from '../lib/types';
import { newAccount, processPrice, type Account } from '../lib/paper';
import type { Condition } from '../lib/scanner';

export type IndicatorKey = 'sma20' | 'sma50' | 'sma200' | 'bbands' | 'volume' | 'rsi' | 'macd';
export type DrawTool = 'cursor' | 'trend' | 'channel' | 'measure' | 'hline';
export type LayoutPreset = 'trader' | 'quad' | 'scanner';
export type TradingMode = 'paper' | 'live';

export interface Note { text: string; updatedAt: number; x: number; y: number; visible: boolean }

export interface Toast { id: number; text: string; tone: 'up' | 'down' | 'info' }

interface WorkspaceState {
  symbol: string;
  watchlist: string;
  customWatchlist: string[];
  chartType: 'candles' | 'line';
  indicators: Record<IndicatorKey, boolean>;
  tool: DrawTool;
  drawings: Record<string, Drawing[]>;
  notes: Record<string, Note>;
  layout: LayoutPreset;
  sizes: { left: number; right: number; bottom: number };
  quadSymbols: string[];
  mode: TradingMode;
  paper: Account;
  scanConditions: Condition[];
  savedScans: { name: string; conditions: Condition[] }[];
  strategy: { symbol: string; dte: number; legs: OptionLeg[]; showOnChart: boolean };
  toasts: Toast[];

  setSymbol: (s: string) => void;
  set: <K extends keyof WorkspaceState>(k: K, v: WorkspaceState[K]) => void;
  toggleIndicator: (k: IndicatorKey) => void;
  addDrawing: (symbol: string, d: Drawing) => void;
  clearDrawings: (symbol: string) => void;
  saveNote: (symbol: string, patch: Partial<Note>) => void;
  placeOrders: (orders: Order[]) => void;
  modifyOrderPrice: (id: string, price: number) => void;
  cancelOrder: (id: string) => void;
  onPrice: (symbol: string, price: number) => void;
  resetPaper: () => void;
  toast: (text: string, tone?: Toast['tone']) => void;
}

let toastSeq = 0;

export const useWorkspace = create<WorkspaceState>()(
  persist(
    (set, get) => ({
      symbol: 'NVDA',
      watchlist: 'Mega Caps',
      customWatchlist: ['AAPL', 'NVDA', 'PLTR'],
      chartType: 'candles',
      indicators: { sma20: true, sma50: true, sma200: false, bbands: false, volume: true, rsi: true, macd: false },
      tool: 'cursor',
      drawings: {},
      notes: {},
      layout: 'trader',
      sizes: { left: 250, right: 360, bottom: 260 },
      quadSymbols: ['SPY', 'QQQ', 'AAPL', 'MSFT'],
      mode: 'paper',
      paper: newAccount(),
      scanConditions: [],
      savedScans: [],
      strategy: { symbol: 'NVDA', dte: 30, legs: [], showOnChart: true },
      toasts: [],

      setSymbol: (symbol) => set({ symbol }),
      set: (k, v) => set({ [k]: v } as Partial<WorkspaceState>),
      toggleIndicator: (k) => set((s) => ({ indicators: { ...s.indicators, [k]: !s.indicators[k] } })),
      addDrawing: (symbol, d) => set((s) => ({ drawings: { ...s.drawings, [symbol]: [...(s.drawings[symbol] ?? []), d] } })),
      clearDrawings: (symbol) => set((s) => ({ drawings: { ...s.drawings, [symbol]: [] } })),
      saveNote: (symbol, patch) => set((s) => {
        const prev = s.notes[symbol] ?? { text: '', updatedAt: 0, x: 24, y: 24, visible: true };
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
      resetPaper: () => set({ paper: newAccount() }),
      toast: (text, tone = 'info') => {
        const id = ++toastSeq;
        set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, tone }] }));
        setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 4000);
      },
    }),
    {
      name: 'chartdesk-workspace',
      version: 1,
      partialize: ({ toasts: _t, tool: _tool, ...rest }) => rest,
    },
  ),
);
