import { useEffect } from 'react';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { WATCHLISTS } from '../data/universe';
import { ibkr } from './ibkr';

/** Drives prices: simulated ticks (1s) or IBKR snapshots (2s), then runs the paper-trading engine. */
export function useMarketFeed() {
  const source = useMarket((s) => s.source);

  useEffect(() => {
    const runEngine = () => {
      const { bars } = useMarket.getState();
      const ws = useWorkspace.getState();
      const syms = new Set(ws.paper.orders.filter((o) => o.status === 'WORKING').map((o) => o.symbol));
      syms.forEach((s) => { const b = bars[s]; if (b?.length) ws.onPrice(s, b[b.length - 1].close); });
    };

    if (source === 'mock') {
      const id = setInterval(() => { useMarket.getState().mockTick(); runEngine(); }, 1000);
      return () => clearInterval(id);
    }

    let busy = false;
    const poll = async () => {
      if (busy) return;
      busy = true;
      try {
        const ws = useWorkspace.getState();
        const wanted = new Set([ws.symbol, ...ws.quadSymbols, ...(WATCHLISTS[ws.watchlist] ?? ws.customWatchlist), ...ws.paper.orders.filter((o) => o.status === 'WORKING').map((o) => o.symbol)]);
        const quotes = await ibkr.snapshot([...wanted]);
        const m = useMarket.getState();
        quotes.forEach((q) => q.last && m.applyQuote(q.symbol, q.last, q.volume));
        runEngine();
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
