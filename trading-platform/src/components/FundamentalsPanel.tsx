import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { infoFor } from '../data/universe';
import { volBuzz } from './WatchlistPanel';
import { compactNum, pct, tone } from '../lib/format';
import { PanelHeader } from './ui';

/** Company snapshot computed from the daily series plus the reference fundamentals. */
export function FundamentalsPanel() {
  const symbol = useWorkspace((s) => s.symbol);
  const bars = useMarket((s) => s.bars[symbol]);
  const info = infoFor(symbol);
  if (!bars?.length) return null;
  const last = bars[bars.length - 1].close;
  const ret = (n: number) => (bars.length > n ? ((last - bars[bars.length - 1 - n].close) / bars[bars.length - 1 - n].close) * 100 : null);
  const yearStart = bars.findIndex((b) => new Date(b.time * 1000).getUTCFullYear() === new Date().getUTCFullYear());
  const ytd = yearStart > 0 ? ((last - bars[yearStart - 1].close) / bars[yearStart - 1].close) * 100 : null;
  const year = bars.slice(-252);
  const hi = Math.max(...year.map((b) => b.high)), lo = Math.min(...year.map((b) => b.low));
  const avgVol = year.slice(-50).reduce((a, b) => a + b.volume, 0) / Math.min(50, year.length);
  const dailyRets = year.slice(1).map((b, i) => Math.log(b.close / year[i].close));
  const mean = dailyRets.reduce((a, b) => a + b, 0) / dailyRets.length;
  const hv = Math.sqrt(dailyRets.reduce((a, b) => a + (b - mean) ** 2, 0) / dailyRets.length) * Math.sqrt(252) * 100;

  const rows: [string, React.ReactNode, string?][] = [
    ['Sector', info.sector],
    ['Market cap', `$${compactNum(info.marketCapB * 1e9)}`],
    ['EPS growth (1y)', pct(info.epsGrowth), tone(info.epsGrowth)],
    ['52-week high', hi.toFixed(2)],
    ['52-week low', lo.toFixed(2)],
    ['% from 52w high', pct(((last - hi) / hi) * 100), tone(last - hi)],
    ['Avg volume (50d)', compactNum(avgVol)],
    ['Vol Buzz', (() => { const v = volBuzz(bars.map((b) => b.volume)); return v === null ? '—' : pct(v); })()],
    ['Historical volatility', `${hv.toFixed(1)}%`],
  ];
  const perf: [string, number | null][] = [['1 Week', ret(5)], ['1 Month', ret(21)], ['3 Months', ret(63)], ['6 Months', ret(126)], ['YTD', ytd], ['1 Year', ret(251)]];

  return (
    <div className="flex h-full flex-col bg-[#0b0e13] text-xs">
      <PanelHeader><span className="font-semibold text-ink-100">{symbol}</span><span className="truncate text-ink-400">· {info.name}</span></PanelHeader>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        <table className="w-full">
          <tbody>
            {rows.map(([k, v, cls]) => (
              <tr key={k} className="border-b border-ink-850"><td className="py-1 text-ink-400">{k}</td><td className={`py-1 text-right font-mono ${cls ?? 'text-ink-100'}`}>{v}</td></tr>
            ))}
          </tbody>
        </table>
        <div>
          <div className="mb-1 text-2xs uppercase tracking-wide text-ink-500">Performance</div>
          <div className="grid grid-cols-3 gap-1.5">
            {perf.map(([k, v]) => (
              <div key={k} className="rounded border border-ink-800 bg-ink-950 px-2 py-1">
                <div className="text-[10px] text-ink-500">{k}</div>
                <div className={`font-mono ${tone(v ?? 0)}`}>{v === null ? '—' : pct(v)}</div>
              </div>
            ))}
          </div>
        </div>
        <p className="text-[10px] text-ink-600">Sector, market cap and EPS growth are reference values for the simulator; price statistics are computed from the chart data.</p>
      </div>
    </div>
  );
}
