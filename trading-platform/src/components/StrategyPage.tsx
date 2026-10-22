import { useEffect, useMemo, useState } from 'react';
import { Copy, FlaskConical, Play, Plus, Radio, Square, Trash2 } from 'lucide-react';
import { useMarket, tfKey } from '../store/market';
import { useWorkspace, type ForwardTest } from '../store/workspace';
import { infoFor, WATCHLISTS } from '../data/universe';
import { newStrategy, TEMPLATES } from '../data/strategyTemplates';
import { backtest, PARAM_LABELS, walkForward, type ParamKey, type ParamRange, type OptimizeMetric, type Stats, type StrategyDef, type Trade } from '../lib/backtest';
import { computeSeries, newConditionId } from '../lib/scanner';
import { isIntraday, TF_SECONDS, TIMEFRAMES, type Timeframe } from '../lib/timeframes';
import { orderId } from '../lib/paper';
import { ftPosition, ftTag } from '../lib/forwardTest';
import { usd, pct, tone } from '../lib/format';
import { ConditionRow } from './ConditionRow';
import { BacktestChart } from './BacktestChart';
import { Split } from './Split';
import { PanelHeader, Tabs, btnCls } from './ui';

const num = 'h-6 rounded border border-ink-700 bg-ink-950 px-1.5 font-mono text-2xs text-ink-100 outline-none focus:border-accent';
const periodsPerYear = (tf: Timeframe) => (tf === 'D' ? 252 : tf === 'W' ? 52 : 252 * ((390 * 60) / TF_SECONDS[tf]));
const fmtTime = (t: number, intraday: boolean) => new Date(t * 1000).toLocaleString([], intraday ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' } : { year: '2-digit', month: 'short', day: 'numeric' });

function useBars(symbol: string, tf: Timeframe) {
  const bars = useMarket((s) => (tf === 'D' ? s.bars[symbol] : s.tfBars[tfKey(symbol, tf)]));
  useEffect(() => useMarket.getState().ensureTf(symbol, tf), [symbol, tf]);
  return bars;
}

// ---- editor ---------------------------------------------------------------------------------

function StrategyEditor({ def, onChange }: { def: StrategyDef; onChange: (d: StrategyDef) => void }) {
  const { strategies, set, saveStrategy, deleteStrategy } = useWorkspace();
  const opt = (v: number | undefined) => (v === undefined ? '' : v);
  const setOpt = (k: 'stopPct' | 'targetPct' | 'trailPct' | 'maxBars') => (e: React.ChangeEvent<HTMLInputElement>) =>
    onChange({ ...def, [k]: e.target.value === '' || +e.target.value <= 0 ? undefined : +e.target.value });
  const rules = (k: 'entry' | 'exit', title: string, hint: string) => (
    <div className="space-y-1">
      <div className="flex items-center text-2xs font-semibold uppercase tracking-wide text-ink-400">
        {title}<span className="ml-1 font-normal normal-case text-ink-600">{hint}</span>
        <button className="ml-auto flex items-center gap-0.5 text-accent hover:underline" onClick={() => onChange({ ...def, [k]: [...def[k], { id: newConditionId(), left: 'rsi14', op: '>', right: { kind: 'value', value: 50 } }] })}><Plus size={11} /> Add rule</button>
      </div>
      {def[k].map((c, i) => (
        <ConditionRow key={c.id} c={c} onChange={(nc) => onChange({ ...def, [k]: def[k].map((x, j) => (j === i ? nc : x)) })} onDelete={() => onChange({ ...def, [k]: def[k].filter((_, j) => j !== i) })} />
      ))}
      {!def[k].length && <div className="rounded border border-dashed border-ink-800 p-2 text-center text-2xs text-ink-600">{k === 'entry' ? 'Add at least one entry rule' : 'No exit rules — exits come from stop / target / trail / max bars'}</div>}
    </div>
  );

  return (
    <div className="flex h-full flex-col bg-ink-900 text-xs">
      <PanelHeader>
        <FlaskConical size={12} className="text-accent" />
        <select className="min-w-0 flex-1 bg-transparent font-semibold text-ink-100 outline-none" value={def.id} onChange={(e) => set('activeStrategy', e.target.value)}>
          {strategies.map((s) => <option key={s.id} value={s.id} className="bg-ink-900">{s.name}</option>)}
        </select>
        <select className="w-24 bg-transparent text-2xs text-accent outline-none" value="" onChange={(e) => { const t = TEMPLATES[+e.target.value]; if (t) saveStrategy(newStrategy(t)); }}>
          <option value="" className="bg-ink-900">+ New…</option>
          {TEMPLATES.map((t, i) => <option key={t.name} value={i} className="bg-ink-900">{t.name}</option>)}
        </select>
        <button title="Duplicate" className="text-ink-400 hover:text-ink-100" onClick={() => saveStrategy({ ...structuredClone(def), id: orderId(), name: `${def.name} (copy)` })}><Copy size={12} /></button>
        <button title="Delete" className="text-ink-400 hover:text-down" onClick={() => confirm(`Delete "${def.name}"?`) && deleteStrategy(def.id)}><Trash2 size={12} /></button>
      </PanelHeader>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        <div className="flex gap-2">
          <input className={`${num} min-w-0 flex-1 font-sans text-xs`} value={def.name} onChange={(e) => onChange({ ...def, name: e.target.value })} aria-label="Strategy name" />
          <div className="flex rounded border border-ink-700 p-0.5">
            {(['long', 'short'] as const).map((d) => (
              <button key={d} onClick={() => onChange({ ...def, direction: d })} className={`rounded px-2 text-2xs capitalize ${def.direction === d ? (d === 'long' ? 'bg-up text-ink-950' : 'bg-down text-white') : 'text-ink-400'}`}>{d}</button>
            ))}
          </div>
        </div>
        {rules('entry', 'Entry', '— all must be true at bar close; fills next open')}
        {rules('exit', 'Exit', '— any true at bar close; fills next open')}
        <div>
          <div className="mb-1 text-2xs font-semibold uppercase tracking-wide text-ink-400">Risk management <span className="font-normal normal-case text-ink-600">(blank = off)</span></div>
          <div className="grid grid-cols-4 gap-1.5 text-2xs text-ink-500">
            <label>Stop %<input type="number" step={0.5} className={`${num} w-full`} value={opt(def.stopPct)} onChange={setOpt('stopPct')} /></label>
            <label>Target %<input type="number" step={0.5} className={`${num} w-full`} value={opt(def.targetPct)} onChange={setOpt('targetPct')} /></label>
            <label>Trail %<input type="number" step={0.5} className={`${num} w-full`} value={opt(def.trailPct)} onChange={setOpt('trailPct')} /></label>
            <label>Max bars<input type="number" step={1} className={`${num} w-full`} value={opt(def.maxBars)} onChange={setOpt('maxBars')} /></label>
          </div>
        </div>
        <div>
          <div className="mb-1 text-2xs font-semibold uppercase tracking-wide text-ink-400">Sizing &amp; costs</div>
          <div className="grid grid-cols-4 gap-1.5 text-2xs text-ink-500">
            <label>Capital<input type="number" className={`${num} w-full`} value={def.capital} onChange={(e) => onChange({ ...def, capital: Math.max(100, +e.target.value) })} /></label>
            <label>Size
              <div className="flex gap-0.5">
                <input type="number" className={`${num} w-full`} value={def.sizing.value} onChange={(e) => onChange({ ...def, sizing: { ...def.sizing, value: Math.max(1, +e.target.value) } })} />
                <select className="h-6 rounded border border-ink-700 bg-ink-950 text-2xs" value={def.sizing.mode} onChange={(e) => onChange({ ...def, sizing: { ...def.sizing, mode: e.target.value as 'percent' | 'shares' } })}>
                  <option value="percent">% eq</option><option value="shares">shs</option>
                </select>
              </div>
            </label>
            <label>Comm $/sh<input type="number" step={0.001} className={`${num} w-full`} value={def.commission} onChange={(e) => onChange({ ...def, commission: Math.max(0, +e.target.value) })} /></label>
            <label>Slippage %<input type="number" step={0.01} className={`${num} w-full`} value={def.slippagePct} onChange={(e) => onChange({ ...def, slippagePct: Math.max(0, +e.target.value) })} /></label>
          </div>
        </div>
        <p className="text-[10px] leading-relaxed text-ink-600">
          Signals use bar closes and fill at the next bar's open (no look-ahead). Stops and targets are checked inside each bar; when both
          are touched in the same bar the stop is assumed first. Gaps through a stop fill at the open. Past results on simulated data
          don't predict future returns.
        </p>
      </div>
    </div>
  );
}

// ---- results --------------------------------------------------------------------------------

function StatGrid({ s, title, cls = '' }: { s: Stats; title?: string; cls?: string }) {
  const pf = s.profitFactor === Infinity ? '∞' : s.profitFactor.toFixed(2);
  const items: [string, string, string?][] = [
    ['Net profit', `${usd(s.netProfit, 0)} (${pct(s.netPct)})`, tone(s.netProfit)],
    ['Buy & hold', pct(s.buyHoldPct), tone(s.buyHoldPct)],
    ['Trades', String(s.trades)],
    ['Win rate', `${s.winRate.toFixed(1)}%`],
    ['Profit factor', pf, s.profitFactor >= 1 ? 'text-up' : 'text-down'],
    ['Avg trade', usd(s.avgTrade, 0), tone(s.avgTrade)],
    ['Avg win / loss', `${pct(s.avgWinPct)} / ${pct(s.avgLossPct)}`],
    ['Max drawdown', `${s.maxDrawdownPct.toFixed(1)}%`, 'text-down'],
    ['Sharpe', s.sharpe.toFixed(2), s.sharpe >= 1 ? 'text-up' : ''],
    ['Exposure', `${s.exposurePct.toFixed(0)}%`],
  ];
  return (
    <div className={cls}>
      {title && <div className="mb-1 text-2xs font-semibold uppercase tracking-wide text-ink-400">{title}</div>}
      <div className="grid grid-cols-2 gap-1 sm:grid-cols-5">
        {items.map(([k, v, c]) => (
          <div key={k} className="rounded border border-ink-800 bg-ink-950 px-2 py-1">
            <div className="text-[10px] text-ink-500">{k}</div>
            <div className={`font-mono text-xs ${c ?? 'text-ink-100'}`}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TradeTable({ trades, intraday }: { trades: Trade[]; intraday: boolean }) {
  return (
    <table className="w-full whitespace-nowrap font-mono text-2xs">
      <thead className="sticky top-0 bg-ink-950 text-ink-500">
        <tr className="text-right"><th className="px-2 py-1 text-left">#</th><th className="px-2 text-left">Side</th><th className="px-2 text-left">Entry</th><th className="px-2">Price</th><th className="px-2 text-left">Exit</th><th className="px-2">Price</th><th className="px-2">Qty</th><th className="px-2">Bars</th><th className="px-2 text-left">Reason</th><th className="px-2">P&amp;L</th><th className="px-2">%</th></tr>
      </thead>
      <tbody>
        {trades.map((t, i) => (
          <tr key={i} className="border-b border-ink-850 text-right">
            <td className="px-2 py-0.5 text-left text-ink-500">{i + 1}</td>
            <td className={`px-2 text-left ${t.side === 'long' ? 'text-up' : 'text-orange-400'}`}>{t.side}</td>
            <td className="px-2 text-left text-ink-400">{fmtTime(t.entryTime, intraday)}</td><td className="px-2">{t.entryPrice.toFixed(2)}</td>
            <td className="px-2 text-left text-ink-400">{fmtTime(t.exitTime, intraday)}</td><td className="px-2">{t.exitPrice.toFixed(2)}</td>
            <td className="px-2">{t.qty}</td><td className="px-2">{t.bars}</td><td className="px-2 text-left font-sans text-ink-300">{t.reason}</td>
            <td className={`px-2 ${tone(t.pnl)}`}>{usd(t.pnl, 0)}</td><td className={`px-2 ${tone(t.pnl)}`}>{pct(t.pnlPct)}</td>
          </tr>
        ))}
        {!trades.length && <tr><td colSpan={11} className="p-4 text-center font-sans text-ink-500">No trades — loosen the entry rules or test more history.</td></tr>}
      </tbody>
    </table>
  );
}

type Tab = 'summary' | 'trades' | 'walk' | 'universe' | 'forward';

export function StrategyPage() {
  const { strategies, activeStrategy, saveStrategy, symbol, setSymbol } = useWorkspace();
  const def = strategies.find((s) => s.id === activeStrategy) ?? strategies[0];
  const [tf, setTf] = useState<Timeframe>('D');
  const [isPct, setIsPct] = useState(70);
  const [tab, setTab] = useState<Tab>('summary');
  const [runId, setRunId] = useState(0);
  const bars = useBars(symbol, tf);
  const intraday = isIntraday(tf);

  // Snapshot bars when a run starts so results don't shift on every tick.
  const snap = useMemo(() => bars, [symbol, tf, runId, bars?.length, bars?.[0]?.time]); // eslint-disable-line react-hooks/exhaustive-deps
  const series = useMemo(() => (snap ? computeSeries(snap, infoFor(symbol)) : null), [snap, symbol]);
  const split = snap ? Math.floor((snap.length * isPct) / 100) : 0;
  const result = useMemo(() => (snap && series ? backtest(snap, series, def, { periodsPerYear: periodsPerYear(tf) }) : null), [snap, series, def, tf]);
  const isRes = useMemo(() => (snap && series ? backtest(snap, series, def, { to: split - 1, periodsPerYear: periodsPerYear(tf) }) : null), [snap, series, def, split, tf]);
  const oosRes = useMemo(() => (snap && series ? backtest(snap, series, def, { from: split, periodsPerYear: periodsPerYear(tf) }) : null), [snap, series, def, split, tf]);

  // walk-forward
  const [ranges, setRanges] = useState<ParamRange[]>([{ key: 'stopPct', from: 2, to: 10, step: 2 }]);
  const [folds, setFolds] = useState(4);
  const [wfIs, setWfIs] = useState(70);
  const [metric, setMetric] = useState<OptimizeMetric>('sharpe');
  const [wf, setWf] = useState<ReturnType<typeof walkForward> | null>(null);
  const runWalk = () => { if (snap && series) setWf(walkForward(snap, series, def, ranges, { folds, inSamplePct: wfIs, metric, periodsPerYear: periodsPerYear(tf) })); };

  // watchlist sweep
  const [uni, setUni] = useState('Mega Caps');
  const [sweep, setSweep] = useState<{ symbol: string; s: Stats }[]>([]);
  const runSweep = () => {
    const m = useMarket.getState();
    setSweep((WATCHLISTS[uni] ?? []).flatMap((sym) => {
      const b = tf === 'D' ? m.bars[sym] : m.tfBars[tfKey(sym, tf)];
      if (!b?.length) { m.ensureTf(sym, tf); return []; }
      return [{ symbol: sym, s: backtest(b, computeSeries(b, infoFor(sym)), def, { periodsPerYear: periodsPerYear(tf) }).stats }];
    }).sort((a, b) => b.s.netPct - a.s.netPct));
  };

  const showWf = tab === 'walk' && wf && wf.oosEquity.length;
  const chartTrades = showWf ? wf!.oosTrades : result?.trades ?? [];
  const chartEquity = showWf ? wf!.oosEquity : result?.equity ?? [];

  return (
    <Split id="strategy.main" dir="row" initial={0.34}>
      <StrategyEditor def={def} onChange={saveStrategy} />
      <Split id="strategy.right" dir="col" initial={0.55}>
        <div className="flex h-full flex-col">
          <PanelHeader>
            <input className="h-5 w-20 rounded border border-ink-700 bg-ink-950 px-1 text-2xs font-semibold uppercase outline-none" defaultValue={symbol} key={symbol}
              onKeyDown={(e) => { if (e.key === 'Enter') { const s = (e.target as HTMLInputElement).value.trim().toUpperCase(); if (s) { useMarket.getState().ensure(s); setSymbol(s); } } }} aria-label="Test symbol" />
            {TIMEFRAMES.map((t) => <button key={t} onClick={() => setTf(t)} className={`rounded px-1.5 text-2xs ${tf === t ? 'bg-accent text-white' : 'text-ink-400 hover:text-ink-100'}`}>{t}</button>)}
            <span className="ml-2 text-2xs text-ink-500">{snap?.length ?? 0} bars · {snap?.length ? `${fmtTime(snap[0].time, intraday)} → ${fmtTime(snap[snap.length - 1].time, intraday)}` : ''}</span>
            <button onClick={() => setRunId((r) => r + 1)} className={`${btnCls} ml-auto h-5 bg-accent px-2 text-white hover:bg-blue-500`} title="Re-run on the latest data"><Play size={10} /> Run</button>
          </PanelHeader>
          <div className="min-h-0 flex-1">
            {snap && <BacktestChart bars={snap} trades={chartTrades} equity={chartEquity} oosStart={tab === 'summary' ? split : showWf ? wf!.folds[0]?.oosFrom : undefined} intraday={intraday} />}
          </div>
        </div>
        <div className="flex h-full flex-col bg-ink-900">
          <Tabs value={tab} onChange={setTab} items={[
            { id: 'summary', label: 'Summary' }, { id: 'trades', label: `Trades (${result?.trades.length ?? 0})` },
            { id: 'walk', label: 'Walk-forward' }, { id: 'universe', label: 'Watchlist test' }, { id: 'forward', label: <><Radio size={11} /> Forward test</> },
          ]} />
          <div className="min-h-0 flex-1 overflow-auto p-2 text-xs">
            {tab === 'summary' && result && isRes && oosRes && (
              <div className="space-y-3">
                <StatGrid s={result.stats} title={`Full period · ${symbol} · ${tf}`} />
                <div className="flex items-center gap-2 text-2xs text-ink-400">
                  In-sample / out-of-sample split
                  <input type="range" min={30} max={90} step={5} value={isPct} onChange={(e) => setIsPct(+e.target.value)} className="w-40 accent-blue-500" />
                  <span className="font-mono">{isPct}% / {100 - isPct}%</span>
                  <span className="text-ink-600">— a strategy that only works in-sample is probably curve-fit.</span>
                </div>
                <div className="grid gap-3 xl:grid-cols-2">
                  <StatGrid s={isRes.stats} title="In-sample (back test)" />
                  <StatGrid s={oosRes.stats} title="Out-of-sample (forward)" />
                </div>
              </div>
            )}
            {tab === 'trades' && result && <TradeTable trades={result.trades} intraday={intraday} />}
            {tab === 'walk' && (
              <div className="space-y-3">
                <div className="space-y-1">
                  <div className="text-2xs text-ink-400">Optimize these parameters on each in-sample window, then trade the next unseen window with the winners:</div>
                  {ranges.map((r, i) => (
                    <div key={i} className="flex items-center gap-1 text-2xs">
                      <select className="h-6 rounded border border-ink-700 bg-ink-950 px-1" value={r.key} onChange={(e) => setRanges(ranges.map((x, j) => (j === i ? { ...x, key: e.target.value as ParamKey } : x)))}>
                        {(Object.keys(PARAM_LABELS) as ParamKey[]).map((k) => <option key={k} value={k}>{PARAM_LABELS[k]}</option>)}
                      </select>
                      from <input type="number" className={`${num} w-16`} value={r.from} onChange={(e) => setRanges(ranges.map((x, j) => (j === i ? { ...x, from: +e.target.value } : x)))} />
                      to <input type="number" className={`${num} w-16`} value={r.to} onChange={(e) => setRanges(ranges.map((x, j) => (j === i ? { ...x, to: +e.target.value } : x)))} />
                      step <input type="number" className={`${num} w-14`} value={r.step} onChange={(e) => setRanges(ranges.map((x, j) => (j === i ? { ...x, step: +e.target.value } : x)))} />
                      <button className="text-ink-500 hover:text-down" onClick={() => setRanges(ranges.filter((_, j) => j !== i))} aria-label="Remove parameter"><Trash2 size={11} /></button>
                    </div>
                  ))}
                  {ranges.length < 2 && <button className="text-2xs text-accent hover:underline" onClick={() => setRanges([...ranges, { key: 'targetPct', from: 5, to: 20, step: 5 }])}>+ Add parameter</button>}
                </div>
                <div className="flex flex-wrap items-center gap-2 text-2xs text-ink-400">
                  Folds <input type="number" min={2} max={10} className={`${num} w-12`} value={folds} onChange={(e) => setFolds(Math.min(10, Math.max(2, +e.target.value)))} />
                  In-sample % <input type="number" min={50} max={90} className={`${num} w-12`} value={wfIs} onChange={(e) => setWfIs(Math.min(90, Math.max(50, +e.target.value)))} />
                  Optimize for
                  <select className="h-6 rounded border border-ink-700 bg-ink-950 px-1" value={metric} onChange={(e) => setMetric(e.target.value as OptimizeMetric)}>
                    <option value="sharpe">Sharpe</option><option value="netProfit">Net profit</option><option value="profitFactor">Profit factor</option>
                  </select>
                  <button onClick={runWalk} className={`${btnCls} h-6 bg-accent text-white hover:bg-blue-500`}><Play size={10} /> Run walk-forward</button>
                </div>
                {wf && (
                  <>
                    <StatGrid s={wf.oosStats} title="Combined out-of-sample result (what you'd have actually earned)" />
                    <table className="w-full whitespace-nowrap font-mono text-2xs">
                      <thead className="text-ink-500"><tr className="text-right"><th className="px-2 text-left">Fold</th><th className="px-2 text-left">Out-of-sample window</th><th className="px-2 text-left">Best params (in-sample)</th><th className="px-2">IS net</th><th className="px-2">IS Sharpe</th><th className="px-2">OOS net</th><th className="px-2">OOS Sharpe</th><th className="px-2">OOS trades</th></tr></thead>
                      <tbody>
                        {wf.folds.map((f, i) => (
                          <tr key={i} className="border-b border-ink-850 text-right">
                            <td className="px-2 py-0.5 text-left">{i + 1}</td>
                            <td className="px-2 text-left text-ink-400">{fmtTime(snap![f.oosFrom].time, intraday)} → {fmtTime(snap![f.oosTo].time, intraday)}</td>
                            <td className="px-2 text-left font-sans text-ink-300">{Object.entries(f.params).map(([k, v]) => `${PARAM_LABELS[k as ParamKey]} ${v}`).join(', ') || '—'}</td>
                            <td className={`px-2 ${tone(f.is.netPct)}`}>{pct(f.is.netPct)}</td><td className="px-2">{f.is.sharpe.toFixed(2)}</td>
                            <td className={`px-2 ${tone(f.oos.netPct)}`}>{pct(f.oos.netPct)}</td><td className="px-2">{f.oos.sharpe.toFixed(2)}</td><td className="px-2">{f.oos.trades}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!wf.folds.length && <div className="text-2xs text-down">Not enough bars for that many folds — reduce folds or use a longer timeframe.</div>}
                  </>
                )}
              </div>
            )}
            {tab === 'universe' && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-2xs text-ink-400">
                  Test "{def.name}" on every symbol in
                  <select className="h-6 rounded border border-ink-700 bg-ink-950 px-1" value={uni} onChange={(e) => setUni(e.target.value)}>
                    {Object.keys(WATCHLISTS).map((w) => <option key={w}>{w}</option>)}
                  </select>
                  <button onClick={runSweep} className={`${btnCls} h-6 bg-accent text-white hover:bg-blue-500`}><Play size={10} /> Run</button>
                  {sweep.length > 0 && <span>· {sweep.filter((x) => x.s.netPct > 0).length}/{sweep.length} profitable · beat buy &amp; hold on {sweep.filter((x) => x.s.netPct > x.s.buyHoldPct).length}</span>}
                </div>
                <table className="w-full whitespace-nowrap font-mono text-2xs">
                  <thead className="text-ink-500"><tr className="text-right"><th className="px-2 text-left font-sans">Symbol</th><th className="px-2">Net %</th><th className="px-2">Buy &amp; hold</th><th className="px-2">Trades</th><th className="px-2">Win %</th><th className="px-2">PF</th><th className="px-2">Max DD</th><th className="px-2">Sharpe</th></tr></thead>
                  <tbody>
                    {sweep.map(({ symbol: s, s: st }) => (
                      <tr key={s} onClick={() => setSymbol(s)} className="cursor-pointer border-b border-ink-850 text-right hover:bg-ink-850">
                        <td className="px-2 py-0.5 text-left font-sans font-semibold text-ink-100">{s}</td>
                        <td className={`px-2 ${tone(st.netPct)}`}>{pct(st.netPct)}</td><td className={`px-2 ${tone(st.buyHoldPct)}`}>{pct(st.buyHoldPct)}</td>
                        <td className="px-2">{st.trades}</td><td className="px-2">{st.winRate.toFixed(0)}%</td>
                        <td className="px-2">{st.profitFactor === Infinity ? '∞' : st.profitFactor.toFixed(2)}</td><td className="px-2 text-down">{st.maxDrawdownPct.toFixed(1)}%</td><td className="px-2">{st.sharpe.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {tab === 'forward' && <ForwardTestPanel def={def} tf={tf} />}
          </div>
        </div>
      </Split>
    </Split>
  );
}

// ---- forward test (live, paper) -------------------------------------------------------------

function ForwardTestPanel({ def, tf }: { def: StrategyDef; tf: Timeframe }) {
  const { forwardTests, set, updateForwardTest, symbol, paper, cancelOrder, toast } = useWorkspace();
  const bars = useMarket((s) => s.bars);
  const [symbols, setSymbols] = useState(symbol);

  const start = () => {
    const list = [...new Set(symbols.toUpperCase().split(/[\s,]+/).filter(Boolean))];
    if (!list.length || !def.entry.length) { toast('Add symbols and at least one entry rule first', 'down'); return; }
    list.forEach((s) => useMarket.getState().ensureTf(s, tf));
    const t: ForwardTest = { id: orderId(), strategyId: def.id, name: def.name, symbols: list, tf, startedAt: Date.now(), active: true, lastSignal: {}, entryBar: {}, log: [{ time: Date.now(), text: `Started on ${list.join(', ')} (${tf}) — trading the paper account`, tone: 'info' }] };
    set('forwardTests', [t, ...forwardTests]);
  };
  const stop = (t: ForwardTest) => {
    paper.orders.filter((o) => o.tag === ftTag(t) && o.status === 'WORKING').forEach((o) => cancelOrder(o.id));
    updateForwardTest(t.id, (cur) => ({ active: false, log: [...cur.log, { time: Date.now(), text: 'Stopped (open positions stay in the paper account)', tone: 'info' }] }));
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-2xs text-ink-400">
        Run "{def.name}" live on
        <input className={`${num} w-56 font-sans`} value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="AAPL, MSFT, NVDA" aria-label="Symbols" />
        ({tf} bars)
        <button onClick={start} className={`${btnCls} h-6 bg-up text-ink-950 hover:bg-green-400`}><Play size={10} /> Start forward test</button>
      </div>
      <p className="text-[10px] text-ink-600">Checks the rules on every price update using the live (still-forming) bar and places bracket orders in your paper account — at most one entry and one exit per bar per symbol. Works with simulated data or IBKR live data.</p>
      {forwardTests.map((t) => {
        const tag = ftTag(t);
        const per = t.symbols.map((s) => {
          const { qty, cash } = ftPosition(paper.orders, tag, s);
          const last = bars[s]?.[bars[s].length - 1]?.close ?? 0;
          return { s, qty, pnl: cash + qty * last };
        });
        const total = per.reduce((a, x) => a + x.pnl, 0);
        const fills = paper.orders.filter((o) => o.tag === tag && o.status === 'FILLED').length;
        return (
          <div key={t.id} className="rounded border border-ink-800 bg-ink-950/60">
            <div className="flex items-center gap-2 border-b border-ink-800 px-2 py-1">
              <span className={`h-2 w-2 rounded-full ${t.active ? 'animate-pulse bg-up' : 'bg-ink-600'}`} />
              <b className="text-ink-100">{t.name}</b>
              <span className="text-2xs text-ink-500">{t.symbols.join(', ')} · {t.tf} · since {new Date(t.startedAt).toLocaleString()}</span>
              <span className={`ml-auto font-mono ${tone(total)}`}>{usd(total, 0)}</span>
              <span className="text-2xs text-ink-500">{fills} fills</span>
              {t.active
                ? <button onClick={() => stop(t)} className="flex items-center gap-1 rounded bg-down/20 px-2 text-2xs text-down hover:bg-down/30"><Square size={9} /> Stop</button>
                : <button onClick={() => set('forwardTests', forwardTests.filter((x) => x.id !== t.id))} className="text-ink-500 hover:text-down" aria-label="Remove"><Trash2 size={11} /></button>}
            </div>
            <div className="flex flex-wrap gap-3 px-2 py-1 font-mono text-2xs">
              {per.map((x) => <span key={x.s}>{x.s}: <span className={x.qty ? 'text-blue-300' : 'text-ink-500'}>{x.qty ? `${x.qty > 0 ? '+' : ''}${x.qty} sh` : 'flat'}</span> <span className={tone(x.pnl)}>{usd(x.pnl, 0)}</span></span>)}
            </div>
            <div className="max-h-32 overflow-y-auto px-2 pb-1">
              {t.log.slice().reverse().map((l, i) => (
                <div key={i} className="font-mono text-[10px] text-ink-400"><span className="text-ink-600">{new Date(l.time).toLocaleTimeString()}</span> <span className={l.tone === 'up' ? 'text-up' : l.tone === 'down' ? 'text-down' : ''}>{l.text}</span></div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
