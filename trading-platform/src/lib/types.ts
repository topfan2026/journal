export interface Bar {
  time: number; // unix seconds (UTC)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SymbolInfo {
  symbol: string;
  name: string;
  sector: string;
  marketCapB: number; // billions USD
  epsGrowth: number; // trailing 1y EPS growth, %
  basePrice: number;
  vol: number; // annualized volatility used by the mock generator
}

export type OptionRight = 'C' | 'P';

export interface OptionQuote {
  strike: number;
  right: OptionRight;
  bid: number;
  ask: number;
  mid: number;
  iv: number;
  delta: number;
}

export interface OptionLeg {
  id: string;
  right: OptionRight;
  strike: number;
  qty: number; // +long / -short, in contracts
  premium: number; // per share, paid (+) for long, received for short
}

export type OrderSide = 'BUY' | 'SELL';
export type OrderType = 'MKT' | 'LMT' | 'STP' | 'TRAIL';
export type OrderStatus = 'WORKING' | 'FILLED' | 'CANCELLED';

export interface Order {
  id: string;
  symbol: string;
  side: OrderSide;
  type: OrderType;
  qty: number;
  price?: number; // limit/stop trigger
  trailAmount?: number; // for TRAIL, distance in $
  trailAnchor?: number; // best price seen since activation
  ocaGroup?: string;
  parentId?: string; // child brackets activate when parent fills
  status: OrderStatus;
  fillPrice?: number;
  createdAt: number;
  filledAt?: number;
  label?: string;
}

export interface Position {
  symbol: string;
  qty: number;
  avgPrice: number;
}

export interface Drawing {
  id: string;
  kind: 'trend' | 'channel' | 'measure' | 'hline';
  points: { time: number; price: number }[];
}
