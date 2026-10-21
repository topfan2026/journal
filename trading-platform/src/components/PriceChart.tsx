import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart, CrosshairMode, LineStyle,
  type IChartApi, type IPriceLine, type ISeriesApi, type LineData, type Time, type UTCTimestamp,
} from 'lightweight-charts';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { bollinger, closes, macd, rsi, sma, type Series } from '../lib/indicators';
import { analyze } from '../lib/options';
import { logicalToTime, timeToLogical } from '../lib/chartMath';
import type { Bar, Drawing, Order } from '../lib/types';
import { orderId } from '../lib/paper';
import { StickyNote } from './StickyNote';

const C = {
  bg: '#0f131a', grid: '#1a202b', text: '#8592a8', up: '#22c55e', down: '#ef4444',
  sma20: '#f59e0b', sma50: '#3b82f6', sma200: '#a855f7', bb: '#64748b', draw: '#38bdf8',
};

const baseOptions = (height?: number) => ({
  layout: { background: { color: C.bg }, textColor: C.text, fontSize: 11, fontFamily: 'Inter, system-ui, sans-serif' },
  grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
  crosshair: { mode: CrosshairMode.Normal },
  rightPriceScale: { borderColor: '#252d3a', minimumWidth: 64 },
  timeScale: { borderColor: '#252d3a', rightOffset: 6 },
  autoSize: true,
  ...(height ? { height } : {}),
});

const line = (bars: Bar[], s: Series): LineData[] =>
  bars.flatMap((b, i) => (s[i] === null ? [] : [{ time: b.time as UTCTimestamp, value: s[i] as number }]));

/** Like `line`, but keeps a whitespace point for every bar so a sub-pane's logical indices match the price pane's. */
const paddedLine = (bars: Bar[], s: Series): LineData[] =>
  bars.map((b, i) => (s[i] === null ? { time: b.time as UTCTimestamp } : { time: b.time as UTCTimestamp, value: s[i] as number }) as LineData);

interface Api {
  chart: IChartApi;
  main: ISeriesApi<'Candlestick'> | ISeriesApi<'Line'>;
  volume: ISeriesApi<'Histogram'>;
  overlays: Record<'sma20' | 'sma50' | 'sma200' | 'bbU' | 'bbM' | 'bbL', ISeriesApi<'Line'>>;
  rsi?: { chart: IChartApi; series: ISeriesApi<'Line'> };
  macd?: { chart: IChartApi; line: ISeriesApi<'Line'>; signal: ISeriesApi<'Line'>; hist: ISeriesApi<'Histogram'> };
}

interface Menu { x: number; y: number; price: number }

type TimeScale = ReturnType<IChartApi['timeScale']>;

/** logical → x, interpolating between bars (the library returns 0 for fractional indices). */
function lx(ts: TimeScale, l: number): number {
  const i = Math.floor(l);
  const a = ts.logicalToCoordinate(i as never) ?? 0;
  if (l === i) return a;
  const b = ts.logicalToCoordinate((i + 1) as never) ?? a;
  return a + (l - i) * (b - a);
}

/** x → fractional logical index. */
function xl(ts: TimeScale, x: number): number {
  const i = ts.coordinateToLogical(x) ?? 0;
  const a = lx(ts, i), b = lx(ts, i + 1);
  return b === a ? i : i + (x - a) / (b - a);
}

export function PriceChart({ symbol, compact = false }: { symbol: string; compact?: boolean }) {
  const bars = useMarket((s) => s.bars[symbol]);
  const ensure = useMarket((s) => s.ensure);
  const chartType = useWorkspace((s) => s.chartType);
  const indicators = useWorkspace((s) => s.indicators);
  const tool = useWorkspace((s) => s.tool);
  const drawings = useWorkspace((s) => s.drawings[symbol]);
  const orders = useWorkspace((s) => s.paper.orders);
  const position = useWorkspace((s) => s.paper.positions[symbol]);
  const strategy = useWorkspace((s) => s.strategy);
  const ws = useWorkspace.getState;

  const wrapRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);
  const macdRef = useRef<HTMLDivElement>(null);
  const api = useRef<Api | null>(null);
  const priceLines = useRef(new Map<string, IPriceLine>());
  const pending = useRef<{ time: number; price: number }[]>([]);
  const mouse = useRef<{ x: number; y: number } | null>(null);
  const drag = useRef<{ id: string; price: number } | null>(null);
  const dataShape = useRef('');
  const [hover, setHover] = useState<Bar | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);

  const showRsi = !compact && indicators.rsi;
  const showMacd = !compact && indicators.macd;

  // live refs for the imperative draw loop and chart callbacks
  const live = useRef({ bars, drawings, tool, strategy, symbol, orders });
  live.current = { bars, drawings, tool, strategy, symbol, orders };

  useEffect(() => ensure(symbol), [symbol, ensure]);

  const pnl = useMemo(() => {
    if (!bars?.length || !strategy.showOnChart || strategy.symbol !== symbol || !strategy.legs.length) return null;
    const last = bars[bars.length - 1].close;
    return analyze(strategy.legs, last * 0.5, last * 1.5);
  }, [bars, strategy, symbol]);
  const pnlRef = useRef(pnl);
  pnlRef.current = pnl;

  // ---- create charts -------------------------------------------------------------------------
  useEffect(() => {
    if (!mainRef.current) return;
    const chart = createChart(mainRef.current, baseOptions());
    const main = chartType === 'candles'
      ? chart.addCandlestickSeries({ upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down })
      : chart.addLineSeries({ color: '#e6ebf2', lineWidth: 2 });
    const volume = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const ov = (color: string, width: 1 | 2 = 1, style = LineStyle.Solid) =>
      chart.addLineSeries({ color, lineWidth: width, lineStyle: style, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    const a: Api = {
      chart, main, volume,
      overlays: { sma20: ov(C.sma20), sma50: ov(C.sma50), sma200: ov(C.sma200, 2), bbU: ov(C.bb, 1, LineStyle.Dotted), bbM: ov(C.bb, 1, LineStyle.Dashed), bbL: ov(C.bb, 1, LineStyle.Dotted) },
    };

    const sub = (el: HTMLDivElement) => {
      const c = createChart(el, { ...baseOptions(), timeScale: { visible: false, borderColor: '#252d3a' } });
      return c;
    };
    if (showRsi && rsiRef.current) {
      const c = sub(rsiRef.current);
      const s = c.addLineSeries({ color: '#c084fc', lineWidth: 1, priceLineVisible: false });
      s.createPriceLine({ price: 70, color: '#ef444480', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' });
      s.createPriceLine({ price: 30, color: '#22c55e80', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' });
      a.rsi = { chart: c, series: s };
    }
    if (showMacd && macdRef.current) {
      const c = sub(macdRef.current);
      a.macd = {
        chart: c,
        hist: c.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false }),
        line: c.addLineSeries({ color: '#38bdf8', lineWidth: 1, priceLineVisible: false }),
        signal: c.addLineSeries({ color: '#f97316', lineWidth: 1, priceLineVisible: false }),
      };
    }
    // keep sub-panes time-aligned with the main pane
    const subs = [a.rsi?.chart, a.macd?.chart].filter(Boolean) as IChartApi[];
    const sync = (r: { from: number; to: number } | null) => r && subs.forEach((c) => c.timeScale().setVisibleLogicalRange(r));
    chart.timeScale().subscribeVisibleLogicalRangeChange(sync);

    chart.subscribeCrosshairMove((p) => {
      mouse.current = p.point ? { x: p.point.x, y: p.point.y } : null;
      const t = p.time as number | undefined;
      const b = t !== undefined ? live.current.bars?.find((x) => x.time === t) : undefined;
      setHover(b ?? null);
    });

    api.current = a;
    dataShape.current = '';
    priceLines.current.clear();
    return () => {
      chart.remove();
      subs.forEach((c) => c.remove());
      api.current = null;
    };
  }, [chartType, showRsi, showMacd, ws]);

  // ---- data -----------------------------------------------------------------------------------
  useEffect(() => {
    const a = api.current;
    if (!a || !bars?.length) return;
    const c = closes(bars);
    const shape = `${symbol}:${bars.length}:${bars[0].time}:${JSON.stringify(indicators)}`;
    const full = shape !== dataShape.current;
    const put = <T extends { time: Time }>(s: ISeriesApi<'Line'> | ISeriesApi<'Histogram'> | ISeriesApi<'Candlestick'>, data: T[]) => {
      if (full) (s as ISeriesApi<'Line'>).setData(data as unknown as LineData[]);
      else if (data.length) (s as ISeriesApi<'Line'>).update(data[data.length - 1] as unknown as LineData);
    };

    if (chartType === 'candles') put(a.main, bars.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
    else put(a.main, bars.map((b) => ({ time: b.time as UTCTimestamp, value: b.close })));

    const vol = indicators.volume ? bars.map((b) => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? '#22c55e55' : '#ef444455' })) : [];
    if (full || indicators.volume) put(a.volume, vol);

    const tail = full ? bars.length : 1;
    const slice = (s: Series) => line(bars.slice(-tail), s.slice(-tail));
    const ov = a.overlays;
    const set = (s: ISeriesApi<'Line'>, on: boolean, data: () => LineData[]) => (on ? put(s, data()) : full && s.setData([]));
    set(ov.sma20, indicators.sma20, () => slice(sma(c, 20)));
    set(ov.sma50, indicators.sma50, () => slice(sma(c, 50)));
    set(ov.sma200, indicators.sma200, () => slice(sma(c, 200)));
    const bb = indicators.bbands ? bollinger(c) : null;
    set(ov.bbU, !!bb, () => slice(bb!.upper));
    set(ov.bbM, !!bb, () => slice(bb!.mid));
    set(ov.bbL, !!bb, () => slice(bb!.lower));

    const padded = (s: Series) => paddedLine(bars.slice(-tail), s.slice(-tail));
    if (a.rsi) put(a.rsi.series, padded(rsi(c)));
    if (a.macd) {
      const m = macd(c);
      put(a.macd.line, padded(m.line));
      put(a.macd.signal, padded(m.signal));
      put(a.macd.hist, padded(m.hist).map((d) => ('value' in d ? { ...d, color: d.value >= 0 ? '#22c55e99' : '#ef444499' } : d)));
    }
    if (full) {
      dataShape.current = shape;
      a.chart.timeScale().setVisibleLogicalRange({ from: bars.length - (compact ? 90 : 140), to: bars.length + 8 });
    }
  }, [bars, indicators, chartType, symbol, compact, showRsi, showMacd]);

  // make room on the right for the expiration overlay
  const hasPnl = !!pnl;
  useEffect(() => {
    const ts = api.current?.chart.timeScale();
    if (!ts) return;
    ts.applyOptions({ rightOffset: hasPnl ? Math.round((strategy.dte * 252) / 365) + 6 : 6 });
    ts.scrollToRealTime();
  }, [hasPnl, strategy.dte, chartType, showRsi, showMacd]);

  // ---- order + position price lines ----------------------------------------------------------
  useEffect(() => {
    const a = api.current;
    if (!a) return;
    const lines = priceLines.current;
    const want = new Map<string, { price: number; color: string; title: string; style: LineStyle }>();
    for (const o of orders) {
      if (o.symbol !== symbol || o.status !== 'WORKING' || o.price === undefined) continue;
      const color = o.label === 'Target' ? '#22c55e' : o.label === 'Stop' || o.type === 'STP' ? '#ef4444' : o.side === 'BUY' ? '#3b82f6' : '#f59e0b';
      want.set(o.id, { price: drag.current?.id === o.id ? drag.current.price : o.price, color, title: `${o.label ?? ''} ${o.side} ${o.type} ${o.qty}`.trim(), style: o.parentId ? LineStyle.Dotted : LineStyle.Dashed });
    }
    if (position) want.set('pos', { price: position.avgPrice, color: '#e6ebf2', title: `POS ${position.qty > 0 ? '+' : ''}${position.qty}`, style: LineStyle.Solid });
    for (const [id, pl] of lines) if (!want.has(id)) { a.main.removePriceLine(pl); lines.delete(id); }
    for (const [id, w] of want) {
      const opts = { price: w.price, color: w.color, lineWidth: 1 as const, lineStyle: w.style, axisLabelVisible: true, title: w.title };
      const pl = lines.get(id);
      if (pl) pl.applyOptions(opts); else lines.set(id, a.main.createPriceLine(opts));
    }
  }, [orders, position, symbol, chartType, showRsi, showMacd]);

  // ---- overlay canvas: drawings, P&L zones, previews ------------------------------------------
  useEffect(() => {
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const a = api.current, cv = canvasRef.current, host = mainRef.current;
      if (!a || !cv || !host) return;
      const { bars: bs, drawings: ds, tool: t } = live.current;
      const dpr = window.devicePixelRatio || 1;
      const w = host.clientWidth, h = host.clientHeight;
      if (cv.width !== w * dpr || cv.height !== h * dpr) { cv.width = w * dpr; cv.height = h * dpr; cv.style.width = `${w}px`; cv.style.height = `${h}px`; }
      const g = cv.getContext('2d')!;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      if (!bs?.length) return;
      const ts = a.chart.timeScale();
      const paneW = w - a.chart.priceScale('right').width();
      const paneH = h - ts.height();
      g.save();
      g.beginPath(); g.rect(0, 0, paneW, paneH); g.clip();
      const X = (time: number) => lx(ts, timeToLogical(bs, time));
      const Y = (price: number) => a.main.priceToCoordinate(price) ?? 0;

      // option P&L zones at expiration
      const z = pnlRef.current;
      if (z) {
        const lastL = bs.length - 1;
        const x0 = lx(ts, lastL);
        const x1 = lx(ts, lastL + (live.current.strategy.dte * 252) / 365);
        for (const zone of z.zones) {
          const yTop = Y(Math.min(zone.to, 1e7)), yBot = Y(zone.from);
          g.fillStyle = zone.profit ? 'rgba(34,197,94,0.13)' : 'rgba(239,68,68,0.13)';
          g.fillRect(x0, Math.min(yTop, yBot), x1 - x0, Math.abs(yBot - yTop));
        }
        g.setLineDash([6, 4]); g.strokeStyle = '#facc15'; g.lineWidth = 1;
        for (const be of z.breakevens) {
          const y = Y(be);
          g.beginPath(); g.moveTo(0, y); g.lineTo(paneW, y); g.stroke();
          label(g, `BE ${be.toFixed(2)}`, x1 + 4 > paneW - 70 ? paneW - 70 : x1 + 4, y - 3, '#facc15');
        }
        g.setLineDash([2, 3]); g.strokeStyle = '#94a3b8';
        g.beginPath(); g.moveTo(x1, 0); g.lineTo(x1, paneH); g.stroke();
        g.setLineDash([]);
        label(g, `Exp ${live.current.strategy.dte}d`, x1 - 52, 14, '#94a3b8');
      }

      // saved drawings + in-progress preview
      const preview: Drawing | null = t !== 'cursor' && pending.current.length && mouse.current
        ? { id: 'preview', kind: t, points: [...pending.current, { time: logicalToTime(bs, xl(ts, mouse.current.x)), price: a.main.coordinateToPrice(mouse.current.y) ?? 0 }] }
        : null;
      for (const d of [...(ds ?? []), ...(preview ? [preview] : [])]) renderDrawing(g, d, X, Y, paneW, bs, d.id === 'preview');
      g.restore();
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);

  // ---- drag-to-modify orders & context menu -------------------------------------------------
  const hitOrder = (y: number): Order | undefined => {
    const a = api.current;
    if (!a) return;
    return live.current.orders.find((o) => o.symbol === symbol && o.status === 'WORKING' && o.price !== undefined && Math.abs((a.main.priceToCoordinate(o.price) ?? -99) - y) < 6);
  };
  const localY = (e: React.PointerEvent | React.MouseEvent) => e.clientY - mainRef.current!.getBoundingClientRect().top;
  const localX = (e: React.PointerEvent | React.MouseEvent) => e.clientX - mainRef.current!.getBoundingClientRect().left;

  // drawing tools: each click adds an anchor; the shape is saved once it has enough points
  useEffect(() => { pending.current = []; }, [tool, symbol]);
  const addPoint = (e: React.PointerEvent) => {
    const a = api.current, bs = live.current.bars;
    if (!a || !bs?.length) return;
    const price = a.main.coordinateToPrice(localY(e));
    if (price === null) return;
    pending.current.push({ time: logicalToTime(bs, xl(a.chart.timeScale(), localX(e))), price });
    const need = { trend: 2, measure: 2, channel: 3, hline: 1, cursor: Infinity }[tool];
    if (pending.current.length >= need) {
      ws().addDrawing(symbol, { id: orderId(), kind: tool as Drawing['kind'], points: pending.current });
      pending.current = [];
      ws().set('tool', 'cursor');
    }
  };

  const onPointerDownCapture = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    if (tool !== 'cursor') {
      // keep the chart from panning while placing anchors
      e.stopPropagation(); e.preventDefault();
      addPoint(e);
      return;
    }
    const o = hitOrder(localY(e));
    if (!o) return;
    e.stopPropagation(); e.preventDefault();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { id: o.id, price: o.price! };
    api.current?.chart.applyOptions({ handleScroll: false, handleScale: false });
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const a = api.current;
    if (!a || !mainRef.current) return;
    const y = localY(e);
    if (drag.current) {
      const p = a.main.coordinateToPrice(y);
      if (p !== null) {
        drag.current.price = Math.round(p * 100) / 100;
        priceLines.current.get(drag.current.id)?.applyOptions({ price: drag.current.price });
      }
      return;
    }
    if (tool !== 'cursor') mouse.current = { x: localX(e), y };
    mainRef.current.style.cursor = tool !== 'cursor' ? 'crosshair' : hitOrder(y) ? 'ns-resize' : '';
  };
  const onPointerUp = () => {
    if (!drag.current) return;
    const { id, price } = drag.current;
    drag.current = null;
    api.current?.chart.applyOptions({ handleScroll: true, handleScale: true });
    ws().modifyOrderPrice(id, price);
    ws().toast(`Order moved to ${price.toFixed(2)}`);
  };
  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    const p = api.current?.main.coordinateToPrice(localY(e));
    if (p == null) return;
    const rect = wrapRef.current!.getBoundingClientRect();
    setMenu({ x: e.clientX - rect.left, y: e.clientY - rect.top, price: Math.round(p * 100) / 100 });
  };
  const placeAt = (side: 'BUY' | 'SELL', type: 'LMT' | 'STP', price: number) => {
    setMenu(null);
    if (ws().mode === 'live') { ws().toast('Live account is read-only in this app — switch to Paper to trade.', 'down'); return; }
    ws().placeOrders([{ id: orderId(), symbol, side, type, qty: 100, price, status: 'WORKING', createdAt: Date.now(), label: 'Chart' }]);
    ws().toast(`${side} ${type} 100 ${symbol} @ ${price.toFixed(2)} placed — drag the line to adjust`);
  };

  const last = bars?.[bars.length - 1];
  const shown = hover ?? last;
  const prevClose = useMarket((s) => s.prevClose[symbol]);
  const chg = last && prevClose ? ((last.close - prevClose) / prevClose) * 100 : 0;
  const lastPx = last?.close ?? 0;

  return (
    <div ref={wrapRef} className="relative flex h-full flex-col bg-ink-900" onClick={() => menu && setMenu(null)}>
      <div className="flex h-7 shrink-0 items-center gap-3 border-b border-ink-800 px-2 font-mono text-2xs text-ink-400">
        <span className="font-sans text-xs font-semibold text-ink-100">{symbol}</span>
        <span className={chg >= 0 ? 'text-up' : 'text-down'}>{lastPx.toFixed(2)} {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%</span>
        {shown && !compact && (
          <span className="hidden gap-2 md:flex">
            <span>O <b className="text-ink-300">{shown.open.toFixed(2)}</b></span>
            <span>H <b className="text-ink-300">{shown.high.toFixed(2)}</b></span>
            <span>L <b className="text-ink-300">{shown.low.toFixed(2)}</b></span>
            <span>C <b className="text-ink-300">{shown.close.toFixed(2)}</b></span>
            <span>V <b className="text-ink-300">{(shown.volume / 1e6).toFixed(1)}M</b></span>
          </span>
        )}
        {!compact && (
          <span className="ml-auto flex gap-2">
            {indicators.sma20 && <span style={{ color: C.sma20 }}>SMA20</span>}
            {indicators.sma50 && <span style={{ color: C.sma50 }}>SMA50</span>}
            {indicators.sma200 && <span style={{ color: C.sma200 }}>SMA200</span>}
            {indicators.bbands && <span style={{ color: C.bb }}>BB(20,2)</span>}
            {pnl && <span className="text-yellow-400">P&amp;L Zones</span>}
          </span>
        )}
      </div>
      <div
        ref={mainRef}
        className="relative min-h-0 flex-1"
        onPointerDownCapture={onPointerDownCapture}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onContextMenu={onContextMenu}
      >
        <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 z-10" />
        {!compact && <StickyNote symbol={symbol} />}
      </div>
      {showRsi && (
        <div className="relative h-[90px] shrink-0 border-t border-ink-800">
          <span className="absolute left-2 top-1 z-10 text-2xs text-purple-400">RSI(14)</span>
          <div ref={rsiRef} className="h-full" />
        </div>
      )}
      {showMacd && (
        <div className="relative h-[90px] shrink-0 border-t border-ink-800">
          <span className="absolute left-2 top-1 z-10 text-2xs text-sky-400">MACD(12,26,9)</span>
          <div ref={macdRef} className="h-full" />
        </div>
      )}
      {menu && (
        <div className="absolute z-30 w-48 rounded border border-ink-700 bg-ink-850 py-1 text-xs shadow-xl" style={{ left: menu.x, top: menu.y }} onClick={(e) => e.stopPropagation()}>
          <div className="px-3 py-1 text-2xs uppercase tracking-wide text-ink-500">Trade at {menu.price.toFixed(2)}</div>
          {menu.price < lastPx ? (
            <>
              <MenuItem onClick={() => placeAt('BUY', 'LMT', menu.price)} className="text-up">Buy Limit</MenuItem>
              <MenuItem onClick={() => placeAt('SELL', 'STP', menu.price)} className="text-down">Sell Stop</MenuItem>
            </>
          ) : (
            <>
              <MenuItem onClick={() => placeAt('SELL', 'LMT', menu.price)} className="text-down">Sell Limit</MenuItem>
              <MenuItem onClick={() => placeAt('BUY', 'STP', menu.price)} className="text-up">Buy Stop</MenuItem>
            </>
          )}
          <MenuItem onClick={() => { setMenu(null); ws().addDrawing(symbol, { id: orderId(), kind: 'hline', points: [{ time: last!.time, price: menu.price }] }); }}>Add horizontal line</MenuItem>
        </div>
      )}
    </div>
  );
}

function MenuItem({ children, onClick, className = '' }: { children: React.ReactNode; onClick: () => void; className?: string }) {
  return <button onClick={onClick} className={`block w-full px-3 py-1 text-left hover:bg-ink-700 ${className}`}>{children}</button>;
}

function label(g: CanvasRenderingContext2D, text: string, x: number, y: number, color: string) {
  g.font = '10px Inter, system-ui, sans-serif';
  const w = g.measureText(text).width + 8;
  g.fillStyle = 'rgba(15,19,26,0.85)';
  g.fillRect(x - 2, y - 11, w, 14);
  g.fillStyle = color;
  g.fillText(text, x + 2, y);
}

function renderDrawing(
  g: CanvasRenderingContext2D, d: Drawing,
  X: (t: number) => number, Y: (p: number) => number, paneW: number, bars: Bar[], preview: boolean,
) {
  g.strokeStyle = preview ? '#38bdf8aa' : C.draw;
  g.lineWidth = 1.5;
  const [p0, p1, p2] = d.points;
  const seg = (a: { x: number; y: number }, b: { x: number; y: number }) => { g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke(); };
  const pt = (p: { time: number; price: number }) => ({ x: X(p.time), y: Y(p.price) });
  if (d.kind === 'hline' && p0) {
    const y = Y(p0.price);
    seg({ x: 0, y }, { x: paneW, y });
    label(g, p0.price.toFixed(2), 4, y - 3, C.draw);
    return;
  }
  if (!p1) return;
  const a = pt(p0), b = pt(p1);
  if (d.kind === 'trend') { seg(a, b); return; }
  if (d.kind === 'channel') {
    seg(a, b);
    if (p2) {
      // parallel line through the third point, using the slope of the base line
      const slope = (p1.price - p0.price) / Math.max(1e-9, timeToLogical(bars, p1.time) - timeToLogical(bars, p0.time));
      const off = p2.price - (p0.price + slope * (timeToLogical(bars, p2.time) - timeToLogical(bars, p0.time)));
      const a2 = { x: a.x, y: Y(p0.price + off) }, b2 = { x: b.x, y: Y(p1.price + off) };
      seg(a2, b2);
      g.fillStyle = 'rgba(56,189,248,0.07)';
      g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.lineTo(b2.x, b2.y); g.lineTo(a2.x, a2.y); g.closePath(); g.fill();
    }
    return;
  }
  if (d.kind === 'measure') {
    const up = p1.price >= p0.price;
    g.fillStyle = up ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)';
    g.fillRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
    g.strokeStyle = up ? C.up : C.down;
    seg(a, b);
    const dp = p1.price - p0.price;
    const nBars = Math.round(timeToLogical(bars, p1.time) - timeToLogical(bars, p0.time));
    label(g, `${dp >= 0 ? '+' : ''}${dp.toFixed(2)} (${((dp / p0.price) * 100).toFixed(2)}%)  ${nBars} bars`, b.x + 6, b.y, up ? C.up : C.down);
  }
}
