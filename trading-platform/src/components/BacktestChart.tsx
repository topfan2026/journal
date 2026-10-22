import { useEffect, useRef } from 'react';
import { createChart, CrosshairMode, LineStyle, type IChartApi, type SeriesMarker, type Time, type UTCTimestamp } from 'lightweight-charts';
import type { Bar } from '../lib/types';
import type { EquityPoint, Trade } from '../lib/backtest';

const opts = {
  layout: { background: { color: '#0b0e13' }, textColor: '#8592a8', fontSize: 11, fontFamily: 'Inter, system-ui, sans-serif' },
  grid: { vertLines: { color: '#161b24' }, horzLines: { color: '#161b24' } },
  crosshair: { mode: CrosshairMode.Normal },
  rightPriceScale: { borderColor: '#252d3a', minimumWidth: 72 },
  timeScale: { borderColor: '#252d3a', rightOffset: 4 },
  autoSize: true,
};

/** Price with entry/exit markers on top; strategy equity vs. buy & hold below. */
export function BacktestChart({ bars, trades, equity, oosStart, intraday }: { bars: Bar[]; trades: Trade[]; equity: EquityPoint[]; oosStart?: number; intraday: boolean }) {
  const topRef = useRef<HTMLDivElement>(null);
  const botRef = useRef<HTMLDivElement>(null);
  const charts = useRef<{ top: IChartApi; bot: IChartApi } | null>(null);

  useEffect(() => {
    if (!topRef.current || !botRef.current) return;
    const top = createChart(topRef.current, { ...opts, timeScale: { ...opts.timeScale, timeVisible: intraday } });
    const bot = createChart(botRef.current, { ...opts, timeScale: { ...opts.timeScale, visible: true, timeVisible: intraday } });
    top.timeScale().subscribeVisibleLogicalRangeChange((r) => r && bot.timeScale().setVisibleLogicalRange(r));
    charts.current = { top, bot };
    return () => { top.remove(); bot.remove(); charts.current = null; };
  }, [intraday]);

  useEffect(() => {
    const c = charts.current;
    if (!c || !bars.length) return;
    // rebuild series each run (cheap, and avoids stale markers)
    const top = c.top, bot = c.bot;
    const candles = top.addCandlestickSeries({ upColor: '#22c55e', downColor: '#ef4444', borderVisible: false, wickUpColor: '#22c55e', wickDownColor: '#ef4444' });
    candles.setData(bars.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
    const markers: SeriesMarker<Time>[] = [];
    for (const t of trades) {
      const long = t.side === 'long';
      markers.push({ time: t.entryTime as UTCTimestamp, position: long ? 'belowBar' : 'aboveBar', color: long ? '#22c55e' : '#f97316', shape: long ? 'arrowUp' : 'arrowDown', text: long ? 'B' : 'S' });
      markers.push({ time: t.exitTime as UTCTimestamp, position: long ? 'aboveBar' : 'belowBar', color: t.pnl >= 0 ? '#38bdf8' : '#ef4444', shape: 'circle', text: `${t.pnlPct >= 0 ? '+' : ''}${t.pnlPct.toFixed(1)}%` });
    }
    if (oosStart !== undefined && bars[oosStart]) markers.push({ time: bars[oosStart].time as UTCTimestamp, position: 'aboveBar', color: '#facc15', shape: 'square', text: 'Out-of-sample →' });
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    candles.setMarkers(markers);

    // equity pane: pad with whitespace so logical indices line up with the price pane
    const byTime = new Map(equity.map((p) => [p.time, p.value]));
    const first = equity[0];
    const eq = bot.addAreaSeries({ lineColor: '#3b82f6', topColor: 'rgba(59,130,246,0.25)', bottomColor: 'rgba(59,130,246,0.02)', lineWidth: 2, priceLineVisible: false });
    eq.setData(bars.map((b) => (byTime.has(b.time) ? { time: b.time as UTCTimestamp, value: byTime.get(b.time)! } : { time: b.time as UTCTimestamp })) as never);
    const bh = bot.addLineSeries({ color: '#64748b', lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
    if (first) {
      const startIdx = bars.findIndex((b) => b.time === first.time);
      const base = bars[startIdx]?.close ?? 1;
      bh.setData(bars.map((b, i) => (i >= startIdx && byTime.has(b.time) ? { time: b.time as UTCTimestamp, value: (first.value * b.close) / base } : { time: b.time as UTCTimestamp })) as never);
    }
    top.timeScale().fitContent();
    return () => {
      // the chart itself may already be gone (it is torn down first on unmount)
      if (charts.current?.top !== top) return;
      top.removeSeries(candles); bot.removeSeries(eq); bot.removeSeries(bh);
    };
  }, [bars, trades, equity, oosStart]);

  return (
    <div className="flex h-full flex-col bg-[#0b0e13]">
      <div className="relative min-h-0 flex-[3]"><div ref={topRef} className="h-full" /></div>
      <div className="relative min-h-0 flex-[2] border-t border-ink-800">
        <span className="absolute left-2 top-1 z-10 text-2xs text-ink-400"><span className="text-blue-400">━ Strategy equity</span> &nbsp; <span className="text-slate-500">┄ Buy &amp; hold</span></span>
        <div ref={botRef} className="h-full" />
      </div>
    </div>
  );
}
