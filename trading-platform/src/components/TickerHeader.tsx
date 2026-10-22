import { Bell, Flag, Star } from 'lucide-react';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { infoFor } from '../data/universe';
import { volBuzz, FLAG_CLS } from './WatchlistPanel';
import { compactNum, pct, tone } from '../lib/format';

/** Position of `v` within [lo, hi] as a small range bar. */
function RangeBar({ lo, hi, v, label }: { lo: number; hi: number; v: number; label: string }) {
  const f = hi > lo ? Math.min(1, Math.max(0, (v - lo) / (hi - lo))) : 0.5;
  return (
    <div className="w-32 shrink-0">
      <div className="flex justify-between text-[9px] text-ink-500"><span>{label}</span><span>{lo.toFixed(2)} – {hi.toFixed(2)}</span></div>
      <div className="relative mt-0.5 h-1 rounded bg-gradient-to-r from-down/60 via-ink-600 to-up/60">
        <div className="absolute -top-0.5 h-2 w-0.5 rounded bg-ink-100" style={{ left: `calc(${f * 100}% - 1px)` }} />
      </div>
    </div>
  );
}

function Cell({ k, v, cls = 'text-ink-100' }: { k: string; v: React.ReactNode; cls?: string }) {
  return (
    <div className="shrink-0">
      <div className="text-[9px] uppercase tracking-wide text-ink-500">{k}</div>
      <div className={`font-mono text-xs ${cls}`}>{v}</div>
    </div>
  );
}

/** Quote and key details for the selected symbol, shown above every page. */
export function TickerHeader() {
  const { symbol, flags, customWatchlist, alerts, cycleFlag, toggleFavorite } = useWorkspace();
  const bars = useMarket((s) => s.bars[symbol]);
  const prev = useMarket((s) => s.prevClose[symbol]);
  const quote = useMarket((s) => s.quotes[symbol]);
  const source = useMarket((s) => s.source);
  const info = infoFor(symbol);
  if (!bars?.length) return <div className="h-12 shrink-0 border-b border-ink-800 bg-ink-950 px-3 py-2 text-xs text-ink-500">Loading {symbol}…</div>;

  const today = bars[bars.length - 1];
  const last = today.close;
  const chg = prev ? last - prev : 0;
  const chgPct = prev ? (chg / prev) * 100 : 0;
  const year = bars.slice(-252);
  const hi52 = Math.max(...year.map((b) => b.high)), lo52 = Math.min(...year.map((b) => b.low));
  const avgVol = bars.slice(-51, -1).reduce((a, b) => a + b.volume, 0) / Math.min(50, bars.length - 1 || 1);
  const buzz = volBuzz(bars.map((b) => b.volume));
  // simulated spread when no live quote: ~1bp, at least a cent
  const half = Math.max(0.01, +(last * 0.00005).toFixed(2));
  const bid = quote?.bid ?? +(last - half).toFixed(2);
  const ask = quote?.ask ?? +(last + half).toFixed(2);
  const fav = customWatchlist.includes(symbol);
  const flag = flags[symbol];
  const symAlerts = alerts.filter((a) => a.symbol === symbol && !a.triggeredAt).length;

  return (
    <div className="flex h-12 shrink-0 items-center gap-5 overflow-x-auto border-b border-ink-800 bg-ink-950 px-3">
      <div className="flex shrink-0 items-center gap-2">
        <button onClick={() => cycleFlag(symbol)} title="Flag (click to cycle colors)"><Flag size={13} className={flag ? `${FLAG_CLS[flag]} fill-current` : 'text-ink-600 hover:text-ink-400'} /></button>
        <button onClick={() => toggleFavorite(symbol)} title={fav ? 'Remove from My Favorites' : 'Add to My Favorites (Shift+V)'}><Star size={13} className={fav ? 'fill-yellow-400 text-yellow-400' : 'text-ink-600 hover:text-ink-400'} /></button>
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-bold leading-none text-ink-100">{symbol}</span>
            <span className="max-w-[220px] truncate text-xs text-ink-300">{info.name}</span>
          </div>
          <div className="text-[10px] text-ink-500">{info.sector} · {source === 'ibkr' ? 'IBKR live' : 'Simulated'}{symAlerts ? <> · <Bell size={9} className="inline text-yellow-300" /> {symAlerts}</> : null}</div>
        </div>
      </div>
      <div className="flex shrink-0 items-baseline gap-2">
        <span className="font-mono text-2xl font-semibold leading-none text-ink-100">{last.toFixed(2)}</span>
        <span className={`font-mono text-sm ${tone(chg)}`}>{chg >= 0 ? '+' : ''}{chg.toFixed(2)}</span>
        <span className={`rounded px-1 font-mono text-xs ${chg >= 0 ? 'bg-up/15 text-up' : 'bg-down/15 text-down'}`}>{pct(chgPct)}</span>
      </div>
      <Cell k="Bid × Ask" v={<>{bid?.toFixed(2)} <span className="text-ink-500">×</span> {ask?.toFixed(2)}</>} />
      <Cell k="Open" v={today.open.toFixed(2)} />
      <Cell k="High" v={today.high.toFixed(2)} />
      <Cell k="Low" v={today.low.toFixed(2)} />
      <Cell k="Prev close" v={prev?.toFixed(2) ?? '—'} />
      <Cell k="Volume" v={compactNum(today.volume)} />
      <Cell k="Avg vol (50d)" v={compactNum(avgVol)} />
      <Cell k="Vol Buzz" v={buzz === null ? '—' : pct(buzz)} cls={buzz !== null && buzz > 50 ? 'text-up' : buzz !== null && buzz < -30 ? 'text-down' : 'text-ink-100'} />
      <RangeBar label="Day" lo={today.low} hi={today.high} v={last} />
      <RangeBar label="52 wk" lo={lo52} hi={hi52} v={last} />
      <Cell k="Mkt cap" v={info.marketCapB ? `$${compactNum(info.marketCapB * 1e9)}` : '—'} />
      <Cell k="EPS gr" v={pct(info.epsGrowth)} cls={tone(info.epsGrowth)} />
    </div>
  );
}
