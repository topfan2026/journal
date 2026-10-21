import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart, CrosshairMode, LineStyle, PriceScaleMode,
  type IChartApi, type IPriceLine, type ISeriesApi, type LineData, type SeriesType, type UTCTimestamp,
} from 'lightweight-charts';
import { Bell, ChevronDown, Minus, Plus, Settings2 } from 'lucide-react';
import { selectBars, useMarket } from '../store/market';
import { useWorkspace, type ChartType, type IndicatorKey } from '../store/workspace';
import { bollinger, closes, ema, macd, rsi, sma, stochastic, type Series } from '../lib/indicators';
import { analyze } from '../lib/options';
import { logicalToTime, timeToLogical } from '../lib/chartMath';
import { isIntraday, TF_LABEL, TF_SECONDS, TIMEFRAMES, type Timeframe } from '../lib/timeframes';
import type { Bar, Drawing, Order } from '../lib/types';
import { orderId } from '../lib/paper';
import { infoFor } from '../data/universe';
import { StickyNote } from './StickyNote';
import { QuickOrder } from './QuickOrder';

const C = {
  bg: '#0b0e13', grid: '#161b24', text: '#8592a8', up: '#22c55e', down: '#ef4444',
  sma20: '#f59e0b', sma50: '#3b82f6', sma200: '#a855f7', ema9: '#f472b6', ema21: '#2dd4bf', bb: '#64748b', draw: '#38bdf8', alert: '#facc15',
};

export const INDICATORS: { key: IndicatorKey; label: string; color: string; pane: boolean }[] = [
  { key: 'sma20', label: 'Moving Average 20', color: C.sma20, pane: false },
  { key: 'sma50', label: 'Moving Average 50', color: C.sma50, pane: false },
  { key: 'sma200', label: 'Moving Average 200', color: C.sma200, pane: false },
  { key: 'ema9', label: 'Exp. Moving Average 9', color: C.ema9, pane: false },
  { key: 'ema21', label: 'Exp. Moving Average 21', color: C.ema21, pane: false },
  { key: 'bbands', label: 'Bollinger Bands (20, 2)', color: C.bb, pane: false },
  { key: 'volume', label: 'Volume + MA 50', color: '#22c55e', pane: true },
  { key: 'rsi', label: 'RSI (14)', color: '#c084fc', pane: true },
  { key: 'macd', label: 'MACD (12, 26, 9)', color: '#38bdf8', pane: true },
  { key: 'stoch', label: 'Stochastics (14, 3, 3)', color: '#fb923c', pane: true },
];

const baseOptions = () => ({
  layout: { background: { color: C.bg }, textColor: C.text, fontSize: 11, fontFamily: 'Inter, system-ui, sans-serif' },
  grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
  crosshair: { mode: CrosshairMode.Normal },
  rightPriceScale: { borderColor: '#252d3a', minimumWidth: 68 },
  timeScale: { borderColor: '#252d3a', rightOffset: 6 },
  autoSize: true,
});

const line = (bars: Bar[], s: Series): LineData[] =>
  bars.flatMap((b, i) => (s[i] === null ? [] : [{ time: b.time as UTCTimestamp, value: s[i] as number }]));

/** Keeps a whitespace point for every bar so a sub-pane's logical indices match the price pane's. */
const paddedLine = (bars: Bar[], s: Series): LineData[] =>
  bars.map((b, i) => (s[i] === null ? { time: b.time as UTCTimestamp } : { time: b.time as UTCTimestamp, value: s[i] as number }) as LineData);

type AnySeries = ISeriesApi<SeriesType>;
type OverlayKey = 'sma20' | 'sma50' | 'sma200' | 'ema9' | 'ema21' | 'bbU' | 'bbM' | 'bbL';
type PaneKey = 'volume' | 'rsi' | 'macd' | 'stoch';
const PANES: PaneKey[] = ['volume', 'rsi', 'macd', 'stoch'];
const PANE_LABEL: Record<PaneKey, string> = { volume: 'Volume · MA 50', rsi: 'RSI(14)', macd: 'MACD(12,26,9)', stoch: 'Stochastics(14,3,3)' };

interface Pane { chart: IChartApi; series: Record<string, AnySeries> }
interface Api { chart: IChartApi; main: AnySeries; overlays: Record<OverlayKey, ISeriesApi<'Line'>>; panes: Partial<Record<PaneKey, Pane>> }
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

/** Bars between now and an option expiry `dte` calendar days away, for a given timeframe. */
function barsUntil(dte: number, tf: Timeframe) {
  const sessions = (dte * 252) / 365;
  if (tf === 'D') return sessions;
  if (tf === 'W') return dte / 7;
  return sessions * ((390 * 60) / TF_SECONDS[tf]);
}

interface Props {
  symbol: string;
  /** 'linked' follows the workspace timeframe; a fixed value gives this chart its own selector. */
  tf?: 'linked' | Timeframe;
  compact?: boolean;
  /** Hide trading controls (Buy/Sell, order lines) — e.g. the overview page. */
  readOnly?: boolean;
}

export function PriceChart({ symbol, tf: tfProp = 'linked', compact = false, readOnly = false }: Props) {
  const linkedTf = useWorkspace((s) => s.tf);
  const [ownTf, setOwnTf] = useState<Timeframe>(tfProp === 'linked' ? 'D' : tfProp);
  const tf = tfProp === 'linked' ? linkedTf : ownTf;
  const setTf = (t: Timeframe) => (tfProp === 'linked' ? useWorkspace.getState().set('tf', t) : setOwnTf(t));

  const bars = useMarket(selectBars(symbol, tf));
  const ensureTf = useMarket((s) => s.ensureTf);
  const source = useMarket((s) => s.source);
  const chartType = useWorkspace((s) => s.chartType);
  const logScale = useWorkspace((s) => s.logScale);
  const indicators = useWorkspace((s) => s.indicators);
  const tool = useWorkspace((s) => s.tool);
  const drawings = useWorkspace((s) => s.drawings[symbol]);
  const orders = useWorkspace((s) => s.paper.orders);
  const position = useWorkspace((s) => s.paper.positions[symbol]);
  const alerts = useWorkspace((s) => s.alerts);
  const strategy = useWorkspace((s) => s.strategy);
  const ws = useWorkspace.getState;

  const wrapRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const paneRefs = useRef<Partial<Record<PaneKey, HTMLDivElement | null>>>({});
  const api = useRef<Api | null>(null);
  const priceLines = useRef(new Map<string, IPriceLine>());
  const pending = useRef<{ time: number; price: number }[]>([]);
  const mouse = useRef<{ x: number; y: number } | null>(null);
  const drag = useRef<{ id: string; price: number } | null>(null);
  const dataShape = useRef('');
  const [hover, setHover] = useState<Bar | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [indMenu, setIndMenu] = useState(false);
  const [ticket, setTicket] = useState<'BUY' | 'SELL' | null>(null);

  const panes = PANES.filter((p) => indicators[p] && (!compact || p === 'volume'));
  const paneSig = panes.join(',');

  const live = useRef({ bars, drawings, tool, strategy, symbol, orders, tf });
  live.current = { bars, drawings, tool, strategy, symbol, orders, tf };

  useEffect(() => ensureTf(symbol, tf), [symbol, tf, ensureTf]);

  const pnl = useMemo(() => {
    if (readOnly || !bars?.length || !strategy.showOnChart || strategy.symbol !== symbol || !strategy.legs.length) return null;
    const last = bars[bars.length - 1].close;
    return analyze(strategy.legs, last * 0.5, last * 1.5);
  }, [bars, strategy, symbol, readOnly]);
  const pnlRef = useRef(pnl);
  pnlRef.current = pnl;

  // ---- create charts -------------------------------------------------------------------------
  useEffect(() => {
    if (!mainRef.current) return;
    const chart = createChart(mainRef.current, baseOptions());
    const main: AnySeries = chartType === 'candles'
      ? chart.addCandlestickSeries({ upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down })
      : chartType === 'bars'
        ? chart.addBarSeries({ upColor: C.up, downColor: C.down, thinBars: false })
        : chart.addLineSeries({ color: C.up, lineWidth: 2 });
    const ov = (color: string, width: 1 | 2 = 1, style = LineStyle.Solid) =>
      chart.addLineSeries({ color, lineWidth: width, lineStyle: style, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    const a: Api = {
      chart, main, panes: {},
      overlays: {
        sma20: ov(C.sma20), sma50: ov(C.sma50), sma200: ov(C.sma200, 2), ema9: ov(C.ema9), ema21: ov(C.ema21),
        bbU: ov(C.bb, 1, LineStyle.Dotted), bbM: ov(C.bb, 1, LineStyle.Dashed), bbL: ov(C.bb, 1, LineStyle.Dotted),
      },
    };
    for (const key of paneSig ? (paneSig.split(',') as PaneKey[]) : []) {
      const el = paneRefs.current[key];
      if (!el) continue;
      const c = createChart(el, { ...baseOptions(), timeScale: { visible: false, borderColor: '#252d3a' } });
      const L = (color: string) => c.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false });
      const series: Record<string, AnySeries> = {};
      if (key === 'volume') {
        series.hist = c.addHistogramSeries({ priceFormat: { type: 'volume' }, priceLineVisible: false });
        series.ma = c.addLineSeries({ color: '#e6ebf2', lineWidth: 1, priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      } else if (key === 'rsi') {
        series.rsi = L('#c084fc');
        series.rsi.createPriceLine({ price: 70, color: '#ef444480', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' });
        series.rsi.createPriceLine({ price: 30, color: '#22c55e80', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' });
      } else if (key === 'macd') {
        series.hist = c.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
        series.line = L('#38bdf8');
        series.signal = L('#f97316');
      } else {
        series.k = L('#fb923c');
        series.d = L('#60a5fa');
        series.k.createPriceLine({ price: 80, color: '#ef444480', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' });
        series.k.createPriceLine({ price: 20, color: '#22c55e80', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' });
      }
      a.panes[key] = { chart: c, series };
    }
    // keep sub-panes time-aligned with the main pane
    const subs = Object.values(a.panes).map((p) => p!.chart);
    chart.timeScale().subscribeVisibleLogicalRangeChange((r) => r && subs.forEach((c) => c.timeScale().setVisibleLogicalRange(r)));

    chart.subscribeCrosshairMove((p) => {
      mouse.current = p.point ? { x: p.point.x, y: p.point.y } : null;
      const t = p.time as number | undefined;
      setHover(t !== undefined ? live.current.bars?.find((x) => x.time === t) ?? null : null);
    });

    api.current = a;
    dataShape.current = '';
    priceLines.current.clear();
    return () => {
      chart.remove();
      subs.forEach((c) => c.remove());
      api.current = null;
    };
  }, [chartType, paneSig]);

  useEffect(() => {
    const a = api.current;
    if (!a) return;
    a.chart.priceScale('right').applyOptions({ mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal });
    a.chart.applyOptions({ timeScale: { timeVisible: isIntraday(tf), secondsVisible: false } });
  }, [logScale, tf, chartType, paneSig]);

  // ---- data -----------------------------------------------------------------------------------
  useEffect(() => {
    const a = api.current;
    if (!a || !bars?.length) return;
    const c = closes(bars);
    const shape = `${symbol}:${tf}:${bars.length}:${bars[0].time}:${JSON.stringify(indicators)}:${chartType}:${paneSig}`;
    const full = shape !== dataShape.current;
    const put = (s: AnySeries, data: object[]) => {
      if (full) s.setData(data as never);
      else if (data.length) s.update(data[data.length - 1] as never);
    };

    if (chartType === 'line') put(a.main, bars.map((b) => ({ time: b.time, value: b.close })));
    else put(a.main, bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));

    const tail = full ? bars.length : 1;
    const tb = bars.slice(-tail);
    const slice = (s: Series) => line(tb, s.slice(-tail));
    const padded = (s: Series) => paddedLine(tb, s.slice(-tail));
    const ov = a.overlays;
    const set = (s: ISeriesApi<'Line'>, on: boolean, data: () => LineData[]) => (on ? put(s, data()) : full && s.setData([]));
    set(ov.sma20, indicators.sma20, () => slice(sma(c, 20)));
    set(ov.sma50, indicators.sma50, () => slice(sma(c, 50)));
    set(ov.sma200, indicators.sma200, () => slice(sma(c, 200)));
    set(ov.ema9, indicators.ema9, () => slice(ema(c, 9)));
    set(ov.ema21, indicators.ema21, () => slice(ema(c, 21)));
    const bb = indicators.bbands ? bollinger(c) : null;
    set(ov.bbU, !!bb, () => slice(bb!.upper));
    set(ov.bbM, !!bb, () => slice(bb!.mid));
    set(ov.bbL, !!bb, () => slice(bb!.lower));

    const P = a.panes;
    if (P.volume) {
      put(P.volume.series.hist, tb.map((b) => ({ time: b.time, value: b.volume, color: b.close >= b.open ? '#22c55e88' : '#ef444488' })));
      put(P.volume.series.ma, padded(sma(bars.map((b) => b.volume), 50)));
    }
    if (P.rsi) put(P.rsi.series.rsi, padded(rsi(c)));
    if (P.macd) {
      const m = macd(c);
      put(P.macd.series.line, padded(m.line));
      put(P.macd.series.signal, padded(m.signal));
      put(P.macd.series.hist, padded(m.hist).map((d) => ('value' in d ? { ...d, color: d.value >= 0 ? '#22c55e99' : '#ef444499' } : d)));
    }
    if (P.stoch) {
      const st = stochastic(bars);
      put(P.stoch.series.k, padded(st.k));
      put(P.stoch.series.d, padded(st.d));
    }
    if (full) {
      const fresh = !dataShape.current.startsWith(`${symbol}:${tf}:`);
      dataShape.current = shape;
      if (fresh) a.chart.timeScale().setVisibleLogicalRange({ from: bars.length - (compact ? 90 : 150), to: bars.length + 6 });
    }
  }, [bars, indicators, chartType, symbol, tf, compact, paneSig]);

  // make room on the right for the expiration overlay
  const hasPnl = !!pnl;
  useEffect(() => {
    const ts = api.current?.chart.timeScale();
    if (!ts) return;
    ts.applyOptions({ rightOffset: hasPnl ? Math.min(400, Math.round(barsUntil(strategy.dte, tf))) + 6 : 6 });
    if (hasPnl) ts.scrollToRealTime();
  }, [hasPnl, strategy.dte, tf, chartType, paneSig]);

  // ---- order, position and alert price lines -------------------------------------------------
  useEffect(() => {
    const a = api.current;
    if (!a) return;
    const lines = priceLines.current;
    const want = new Map<string, { price: number; color: string; title: string; style: LineStyle }>();
    if (!readOnly) {
      for (const o of orders) {
        if (o.symbol !== symbol || o.status !== 'WORKING' || o.price === undefined) continue;
        const color = o.label === 'Target' ? '#22c55e' : o.label === 'Stop' || o.type === 'STP' ? '#ef4444' : o.side === 'BUY' ? '#3b82f6' : '#f59e0b';
        want.set(o.id, { price: drag.current?.id === o.id ? drag.current.price : o.price, color, title: `${o.label ?? ''} ${o.side} ${o.type} ${o.qty}`.trim(), style: o.parentId ? LineStyle.Dotted : LineStyle.Dashed });
      }
      if (position) want.set('pos', { price: position.avgPrice, color: '#e6ebf2', title: `POS ${position.qty > 0 ? '+' : ''}${position.qty}`, style: LineStyle.Solid });
      for (const al of alerts) {
        if (al.symbol === symbol && !al.triggeredAt) want.set(`al-${al.id}`, { price: al.price, color: C.alert, title: '🔔 Alert', style: LineStyle.SparseDotted });
      }
    }
    for (const [id, pl] of lines) if (!want.has(id)) { a.main.removePriceLine(pl); lines.delete(id); }
    for (const [id, w] of want) {
      const opts = { price: w.price, color: w.color, lineWidth: 1 as const, lineStyle: w.style, axisLabelVisible: true, title: w.title };
      const pl = lines.get(id);
      if (pl) pl.applyOptions(opts); else lines.set(id, a.main.createPriceLine(opts));
    }
  }, [orders, position, alerts, symbol, chartType, paneSig, readOnly]);

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

      const z = pnlRef.current;
      if (z) {
        const lastL = bs.length - 1;
        const x0 = lx(ts, lastL);
        const x1 = lx(ts, lastL + barsUntil(live.current.strategy.dte, live.current.tf));
        for (const zone of z.zones) {
          const yTop = Y(Math.min(zone.to, 1e7)), yBot = Y(Math.max(zone.from, 0.01));
          g.fillStyle = zone.profit ? 'rgba(34,197,94,0.13)' : 'rgba(239,68,68,0.13)';
          g.fillRect(x0, Math.min(yTop, yBot), x1 - x0, Math.abs(yBot - yTop));
        }
        g.setLineDash([6, 4]); g.strokeStyle = '#facc15'; g.lineWidth = 1;
        for (const be of z.breakevens) {
          const y = Y(be);
          g.beginPath(); g.moveTo(0, y); g.lineTo(paneW, y); g.stroke();
          label(g, `BE ${be.toFixed(2)}`, Math.min(x1 + 4, paneW - 70), y - 3, '#facc15');
        }
        g.setLineDash([2, 3]); g.strokeStyle = '#94a3b8';
        g.beginPath(); g.moveTo(x1, 0); g.lineTo(x1, paneH); g.stroke();
        g.setLineDash([]);
        label(g, `Exp ${live.current.strategy.dte}d`, x1 - 52, 14, '#94a3b8');
      }

      const preview: Drawing | null = t !== 'cursor' && pending.current.length && mouse.current
        ? { id: 'preview', kind: t, points: [...pending.current, { time: logicalToTime(bs, xl(ts, mouse.current.x)), price: a.main.coordinateToPrice(mouse.current.y) ?? 0 }] }
        : null;
      for (const d of [...(ds ?? []), ...(preview ? [preview] : [])]) renderDrawing(g, d, X, Y, paneW, bs, d.id === 'preview');
      g.restore();
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);

  // ---- pointer handling: drawing anchors, drag-to-modify orders, context menu ----------------
  const hitOrder = (y: number): Order | undefined => {
    const a = api.current;
    if (!a || readOnly) return;
    return live.current.orders.find((o) => o.symbol === symbol && o.status === 'WORKING' && o.price !== undefined && Math.abs((a.main.priceToCoordinate(o.price) ?? -99) - y) < 6);
  };
  const localY = (e: React.PointerEvent | React.MouseEvent) => e.clientY - mainRef.current!.getBoundingClientRect().top;
  const localX = (e: React.PointerEvent | React.MouseEvent) => e.clientX - mainRef.current!.getBoundingClientRect().left;

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
    if (e.button !== 0 || readOnly) return;
    if (tool !== 'cursor') {
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
    if (readOnly) return;
    const p = api.current?.main.coordinateToPrice(localY(e));
    if (p == null) return;
    const rect = wrapRef.current!.getBoundingClientRect();
    setMenu({ x: Math.min(e.clientX - rect.left, rect.width - 200), y: Math.min(e.clientY - rect.top, rect.height - 160), price: Math.round(p * 100) / 100 });
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
  const chg = last && prevClose ? last.close - prevClose : 0;
  const chgPct = prevClose ? (chg / prevClose) * 100 : 0;
  const lastPx = last?.close ?? 0;
  const info = infoFor(symbol);

  return (
    <div ref={wrapRef} className="relative flex h-full flex-col bg-[#0b0e13]" onClick={() => { menu && setMenu(null); indMenu && setIndMenu(false); }}>
      {/* row 1: symbol, timeframe, chart controls */}
      <div className="flex h-7 shrink-0 items-center gap-1 border-b border-ink-800 px-2 text-xs">
        <button className="mr-1 font-semibold text-up hover:underline" title="Type a symbol anywhere to change it" onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('chartdesk:symbol-entry')); }}>{symbol}</button>
        {TIMEFRAMES.map((t) => (
          <button key={t} onClick={() => setTf(t)} className={`rounded px-1.5 py-0.5 text-2xs ${tf === t ? 'bg-accent text-white' : 'text-ink-400 hover:text-ink-100'}`}>{t}</button>
        ))}
        {!compact && (
          <>
            <span className="mx-1 h-4 w-px bg-ink-700" />
            <select className="h-5 rounded bg-ink-900 px-1 text-2xs text-ink-300 outline-none" value={chartType} onChange={(e) => ws().set('chartType', e.target.value as ChartType)} title="Chart type">
              <option value="candles">Candles</option><option value="bars">OHLC Bars</option><option value="line">Line</option>
            </select>
            <div className="relative">
              <button onClick={(e) => { e.stopPropagation(); setIndMenu(!indMenu); }} className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-2xs text-ink-300 hover:bg-ink-800"><Settings2 size={11} /> Indicators <ChevronDown size={10} /></button>
              {indMenu && (
                <div className="absolute left-0 top-6 z-40 w-56 rounded border border-ink-700 bg-ink-850 py-1 shadow-xl" onClick={(e) => e.stopPropagation()}>
                  {INDICATORS.map((i) => (
                    <label key={i.key} className="flex cursor-pointer items-center gap-2 px-3 py-1 text-xs hover:bg-ink-700">
                      <input type="checkbox" className="accent-blue-500" checked={!!indicators[i.key]} onChange={() => ws().toggleIndicator(i.key)} />
                      <span className="h-0.5 w-3" style={{ background: i.color }} />{i.label}
                    </label>
                  ))}
                </div>
              )}
            </div>
            <button onClick={() => ws().set('logScale', !logScale)} className={`rounded px-1.5 py-0.5 text-2xs ${logScale ? 'bg-ink-700 text-ink-100' : 'text-ink-400 hover:text-ink-100'}`} title="Logarithmic price scale">Log</button>
            {!readOnly && <button onClick={() => last && ws().addAlert(symbol, last.close * 1.02, last.close)} className="rounded px-1.5 py-0.5 text-ink-400 hover:text-yellow-300" title="Add alert 2% above last (or right-click a price)"><Bell size={12} /></button>}
          </>
        )}
        <span className="ml-auto text-2xs text-ink-500">{source === 'ibkr' ? 'IBKR' : 'Simulated'} · {TF_LABEL[tf]}</span>
      </div>
      {/* row 2: quote line */}
      <div className="flex h-5 shrink-0 items-center gap-2 px-2 font-mono text-2xs text-ink-400">
        {shown && (
          <>
            <span>O <b className="text-ink-300">{shown.open.toFixed(2)}</b></span>
            <span>H <b className="text-ink-300">{shown.high.toFixed(2)}</b></span>
            <span>L <b className="text-ink-300">{shown.low.toFixed(2)}</b></span>
            <span className="rounded bg-ink-100 px-1 text-ink-950">{shown.close.toFixed(2)}</span>
            <span className={chg >= 0 ? 'text-up' : 'text-down'}>{chg >= 0 ? '+' : ''}{chg.toFixed(2)} {chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%</span>
            {!compact && <span>Vol <b className="text-ink-300">{(shown.volume / 1e6).toFixed(2)}M</b></span>}
          </>
        )}
        {!compact && (
          <span className="ml-auto flex gap-2">
            {INDICATORS.filter((i) => !i.pane && indicators[i.key]).map((i) => <span key={i.key} style={{ color: i.color }}>{i.label.replace('Moving Average', 'MA').replace('Exp. MA', 'EMA')}</span>)}
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
        {/* watermark */}
        <div className="pointer-events-none absolute inset-0 z-[5] flex select-none flex-col items-center justify-center pr-16 text-center">
          <div className={`font-semibold leading-none text-white/[0.06] ${compact ? 'text-5xl' : 'text-7xl'}`}>{symbol}</div>
          {!compact && <div className="mt-2 text-3xl text-white/[0.06]">{info.name}</div>}
        </div>
        <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 z-10" />
        {!compact && <StickyNote symbol={symbol} />}
        {!readOnly && !compact && (
          <div className="absolute left-2 top-1 z-20 flex gap-1 text-xs font-semibold">
            <button onClick={(e) => { e.stopPropagation(); setTicket('BUY'); }} className="rounded bg-up/15 px-2 py-0.5 text-up hover:bg-up/30">Buy</button>
            <button onClick={(e) => { e.stopPropagation(); setTicket('SELL'); }} className="rounded bg-down/15 px-2 py-0.5 text-down hover:bg-down/30">Sell</button>
            <button onClick={(e) => { e.stopPropagation(); ws().set('page', 'options'); }} className="rounded bg-ink-700/60 px-2 py-0.5 text-ink-300 hover:bg-ink-700">Opt</button>
          </div>
        )}
      </div>
      {panes.map((p) => (
        <div key={p} className={`relative shrink-0 border-t border-ink-800 ${compact ? 'h-[60px]' : 'h-[96px]'}`}>
          <span className="absolute left-2 top-1 z-10 flex items-center gap-1 text-2xs text-ink-400">
            {PANE_LABEL[p]}
            {!compact && <button onClick={() => ws().toggleIndicator(p)} className="text-ink-600 hover:text-down" title="Remove pane"><Minus size={10} /></button>}
          </span>
          <div ref={(el) => { paneRefs.current[p] = el; }} className="h-full" />
        </div>
      ))}
      {ticket && <QuickOrder symbol={symbol} side={ticket} last={lastPx} onClose={() => setTicket(null)} />}
      {menu && (
        <div className="absolute z-30 w-48 rounded border border-ink-700 bg-ink-850 py-1 text-xs shadow-xl" style={{ left: menu.x, top: menu.y }} onClick={(e) => e.stopPropagation()}>
          <div className="px-3 py-1 text-2xs uppercase tracking-wide text-ink-500">At {menu.price.toFixed(2)}</div>
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
          <MenuItem onClick={() => { setMenu(null); ws().addAlert(symbol, menu.price, lastPx); }} className="text-yellow-300">Set price alert</MenuItem>
          <MenuItem onClick={() => { setMenu(null); ws().addDrawing(symbol, { id: orderId(), kind: 'hline', points: [{ time: last!.time, price: menu.price }] }); }}>Add horizontal line</MenuItem>
          <MenuItem onClick={() => { setMenu(null); ws().saveNote(symbol, { visible: true }); }}><Plus size={10} className="mr-1 inline" />Sticky note</MenuItem>
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
  g.fillStyle = 'rgba(11,14,19,0.85)';
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
