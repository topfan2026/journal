import { useEffect } from 'react';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { WATCHLISTS } from '../data/universe';
import { ibkr } from './ibkr';

/** Drives prices: simulated ticks (1s) or IBKR snapshots (2s), then runs the paper engine and alerts. */
export function useMarketFeed() {
  const source = useMarket((s) => s.source);

  useEffect(() => {
    const afterPrices = () => {
      const { bars } = useMarket.getState();
      const ws = useWorkspace.getState();
      const prices: Record<string, number> = {};
      for (const [s, b] of Object.entries(bars)) if (b.length) prices[s] = b[b.length - 1].close;
      const syms = new Set(ws.paper.orders.filter((o) => o.status === 'WORKING').map((o) => o.symbol));
      syms.forEach((s) => prices[s] !== undefined && ws.onPrice(s, prices[s]));
      ws.checkAlerts(prices);
    };

    if (source === 'mock') {
      const id = setInterval(() => { useMarket.getState().mockTick(); afterPrices(); }, 1000);
      return () => clearInterval(id);
    }

    let busy = false;
    const poll = async () => {
      if (busy) return;
      busy = true;
      try {
        const ws = useWorkspace.getState();
        const list = ws.watchlist === 'My Favorites' ? ws.customWatchlist : WATCHLISTS[ws.watchlist] ?? [];
        const wanted = new Set([
          ws.symbol, ...list.slice(0, 40), ...ws.customWatchlist,
          ...ws.paper.orders.filter((o) => o.status === 'WORKING').map((o) => o.symbol),
          ...ws.alerts.filter((a) => !a.triggeredAt).map((a) => a.symbol),
        ]);
        const quotes = await ibkr.snapshot([...wanted].slice(0, 50));
        const m = useMarket.getState();
        quotes.forEach((q) => q.last && m.applyQuote(q.symbol, q.last, q.volume));
        afterPrices();
      } catch {
        /* gateway hiccup — keep last prices and retry next interval */
      } finally {
        busy = false;
      }
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, [source]);
}
