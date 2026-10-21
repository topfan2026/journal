import type { SymbolInfo } from '../lib/types';

export const UNIVERSE: SymbolInfo[] = [
  { symbol: 'AAPL', name: 'Apple Inc.', sector: 'Technology', marketCapB: 3450, epsGrowth: 9.8, basePrice: 228, vol: 0.24 },
  { symbol: 'MSFT', name: 'Microsoft Corp.', sector: 'Technology', marketCapB: 3200, epsGrowth: 17.5, basePrice: 425, vol: 0.22 },
  { symbol: 'NVDA', name: 'NVIDIA Corp.', sector: 'Technology', marketCapB: 3350, epsGrowth: 112.0, basePrice: 138, vol: 0.5 },
  { symbol: 'AMZN', name: 'Amazon.com Inc.', sector: 'Consumer Disc.', marketCapB: 1980, epsGrowth: 64.2, basePrice: 188, vol: 0.3 },
  { symbol: 'GOOGL', name: 'Alphabet Inc.', sector: 'Communication', marketCapB: 2050, epsGrowth: 31.0, basePrice: 166, vol: 0.28 },
  { symbol: 'META', name: 'Meta Platforms', sector: 'Communication', marketCapB: 1460, epsGrowth: 58.4, basePrice: 575, vol: 0.36 },
  { symbol: 'TSLA', name: 'Tesla Inc.', sector: 'Consumer Disc.', marketCapB: 700, epsGrowth: -22.5, basePrice: 220, vol: 0.6 },
  { symbol: 'AVGO', name: 'Broadcom Inc.', sector: 'Technology', marketCapB: 810, epsGrowth: 24.1, basePrice: 172, vol: 0.42 },
  { symbol: 'JPM', name: 'JPMorgan Chase', sector: 'Financials', marketCapB: 620, epsGrowth: 12.3, basePrice: 222, vol: 0.21 },
  { symbol: 'V', name: 'Visa Inc.', sector: 'Financials', marketCapB: 560, epsGrowth: 11.0, basePrice: 285, vol: 0.18 },
  { symbol: 'LLY', name: 'Eli Lilly', sector: 'Healthcare', marketCapB: 830, epsGrowth: 85.0, basePrice: 905, vol: 0.32 },
  { symbol: 'UNH', name: 'UnitedHealth', sector: 'Healthcare', marketCapB: 540, epsGrowth: -4.1, basePrice: 590, vol: 0.25 },
  { symbol: 'XOM', name: 'Exxon Mobil', sector: 'Energy', marketCapB: 520, epsGrowth: -9.5, basePrice: 119, vol: 0.23 },
  { symbol: 'COST', name: 'Costco Wholesale', sector: 'Consumer Staples', marketCapB: 395, epsGrowth: 13.7, basePrice: 890, vol: 0.19 },
  { symbol: 'NFLX', name: 'Netflix Inc.', sector: 'Communication', marketCapB: 330, epsGrowth: 41.0, basePrice: 765, vol: 0.35 },
  { symbol: 'AMD', name: 'Advanced Micro Devices', sector: 'Technology', marketCapB: 250, epsGrowth: 19.2, basePrice: 156, vol: 0.48 },
  { symbol: 'CRM', name: 'Salesforce', sector: 'Technology', marketCapB: 280, epsGrowth: 27.3, basePrice: 292, vol: 0.3 },
  { symbol: 'ADBE', name: 'Adobe Inc.', sector: 'Technology', marketCapB: 225, epsGrowth: 14.6, basePrice: 505, vol: 0.31 },
  { symbol: 'PEP', name: 'PepsiCo', sector: 'Consumer Staples', marketCapB: 230, epsGrowth: 5.2, basePrice: 168, vol: 0.16 },
  { symbol: 'KO', name: 'Coca-Cola', sector: 'Consumer Staples', marketCapB: 300, epsGrowth: 6.8, basePrice: 70, vol: 0.15 },
  { symbol: 'BA', name: 'Boeing Co.', sector: 'Industrials', marketCapB: 95, epsGrowth: -140.0, basePrice: 155, vol: 0.4 },
  { symbol: 'CAT', name: 'Caterpillar', sector: 'Industrials', marketCapB: 190, epsGrowth: 8.9, basePrice: 395, vol: 0.27 },
  { symbol: 'PLTR', name: 'Palantir Technologies', sector: 'Technology', marketCapB: 95, epsGrowth: 120.0, basePrice: 42, vol: 0.65 },
  { symbol: 'SMCI', name: 'Super Micro Computer', sector: 'Technology', marketCapB: 28, epsGrowth: 88.0, basePrice: 48, vol: 0.9 },
  { symbol: 'SPY', name: 'SPDR S&P 500 ETF', sector: 'ETF', marketCapB: 560, epsGrowth: 10.0, basePrice: 580, vol: 0.14 },
  { symbol: 'QQQ', name: 'Invesco QQQ Trust', sector: 'ETF', marketCapB: 300, epsGrowth: 14.0, basePrice: 495, vol: 0.19 },
];

export const WATCHLISTS: Record<string, string[]> = {
  'Mega Caps': ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AVGO'],
  'S&P 500 Leaders': ['AAPL', 'MSFT', 'NVDA', 'JPM', 'V', 'LLY', 'UNH', 'XOM', 'COST', 'PEP', 'KO', 'CAT', 'BA'],
  'NASDAQ 100': ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AVGO', 'NFLX', 'AMD', 'ADBE', 'COST', 'PEP', 'PLTR', 'SMCI'],
  'ETFs': ['SPY', 'QQQ'],
};

export const infoFor = (symbol: string): SymbolInfo =>
  UNIVERSE.find((s) => s.symbol === symbol) ?? {
    symbol, name: symbol, sector: '—', marketCapB: 0, epsGrowth: 0, basePrice: 100, vol: 0.3,
  };
