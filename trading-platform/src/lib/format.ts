export const usd = (n: number, digits = 2) =>
  (n < 0 ? '-' : '') + '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const pct = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
export const compactNum = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(0)}K` : n.toFixed(0);
export const tone = (n: number) => (n > 0 ? 'text-up' : n < 0 ? 'text-down' : 'text-ink-300');
