/**
 * Browser-side client for the local IBKR bridge (server/index.js), which talks to the
 * Interactive Brokers Client Portal Gateway running on your machine. Read-only: market
 * data, accounts and positions. Orders are never routed to IBKR from this app.
 */
import type { Bar } from './types';
import { IBKR_PARAMS, type Timeframe } from './timeframes';

export interface IbkrStatus { reachable: boolean; authenticated: boolean; connected: boolean; message?: string }
export interface IbkrQuote { symbol: string; last: number | null; bid: number | null; ask: number | null; changePct: number | null; volume: number | null }
export interface IbkrPosition { symbol: string; qty: number; avgPrice: number; mktPrice: number; unrealizedPnl: number; assetClass: string }
export interface IbkrSummary { accountId: string; netLiquidation: number | null; buyingPower: number | null; cash: number | null }

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api/ibkr${path}`);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const ibkr = {
  status: () => get<IbkrStatus>('/status'),
  history: (symbol: string, tf: Timeframe) =>
    get<Bar[]>(`/history?symbol=${encodeURIComponent(symbol)}&period=${IBKR_PARAMS[tf].period}&bar=${IBKR_PARAMS[tf].bar}`),
  snapshot: (symbols: string[]) => get<IbkrQuote[]>(`/snapshot?symbols=${encodeURIComponent(symbols.join(','))}`),
  summary: () => get<IbkrSummary>('/summary'),
  positions: () => get<IbkrPosition[]>('/positions'),
};
