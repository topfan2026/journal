import { useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Plus, Save, Search, Wand2, X } from 'lucide-react';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { UNIVERSE, WATCHLISTS, infoFor } from '../data/universe';
import { computeSeries, describe, evaluate, METRIC_LABELS, newConditionId, SCAN_PRESETS, withIds, type Condition, type Metric, type Operator, type ScanRow } from '../lib/scanner';
import { compactNum, pct, tone } from '../lib/format';
import { btnCls, inputCls } from './ui';

type SortKey = keyof ScanRow;
const COLS: { key: SortKey; label: string; num?: boolean }[] = [
  { key: 'symbol', label: 'Symbol' }, { key: 'name', label: 'Name' }, { key: 'sector', label: 'Sector' },
  { key: 'price', label: 'Last', num: true }, { key: 'changePct', label: '% Chg', num: true }, { key: 'volume', label: 'Volume', num: true },
  { key: 'rsi14', label: 'RSI', num: true }, { key: 'macdHist', label: 'MACD H', num: true },
  { key: 'marketCapB', label: 'Mkt Cap', num: true }, { key: 'epsGrowth', label: 'EPS Gr%', num: true },
];

export function ScannerPanel() {
  const bars = useMarket((s) => s.bars);
  const prev = useMarket((s) => s.prevClose);
  const { scanConditions, set, setSymbol, symbol, savedScans } = useWorkspace();
  const [universe, setUniverse] = useState('All');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'changePct', dir: -1 });
  const [wizard, setWizard] = useState(false);

  const symbols = universe === 'All' ? UNIVERSE.map((u) => u.symbol) : WATCHLISTS[universe];

  const rows = useMemo(() => {
    const out: (ScanRow & { pass: boolean })[] = [];
    for (const s of symbols) {
      const b = bars[s];
      if (!b?.length) continue;
      const info = infoFor(s);
      const series = computeSeries(b, info);
      const lastI = b.length - 1;
      const price = b[lastI].close;
      out.push({
        symbol: s, name: info.name, sector: info.sector, price,
        changePct: prev[s] ? ((price - prev[s]) / prev[s]) * 100 : 0,
        volume: b[lastI].volume,
        rsi14: series.rsi14[lastI], macdHist: series.macdHist[lastI],
        marketCapB: info.marketCapB, epsGrowth: info.epsGrowth,
        pass: scanConditions.every((c) => evaluate(series, c)),
      });
    }
    return out;
  }, [bars, prev, symbols, scanConditions]);

  const shown = rows
    .filter((r) => r.pass && (!query || r.symbol.includes(query.toUpperCase()) || r.name.toLowerCase().includes(query.toLowerCase())))
    .sort((a, b) => {
      const av = a[sort.key], bv = b[sort.key];
      if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv) * sort.dir;
      return (((av as number) ?? -Infinity) - ((bv as number) ?? -Infinity)) * sort.dir;
    });

  return (
    <div className="flex h-full flex-col text-xs">
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 px-2 py-1.5">
        <select className={inputCls} value={universe} onChange={(e) => setUniverse(e.target.value)}>
          <option>All</option>{Object.keys(WATCHLISTS).map((w) => <option key={w}>{w}</option>)}
        </select>
        <div className="relative">
          <Search size={12} className="absolute left-2 top-2 text-ink-500" />
          <input className={`${inputCls} w-36 pl-6`} placeholder="Filter…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <select className={inputCls} value="" onChange={(e) => { const p = SCAN_PRESETS.find((x) => x.name === e.target.value); if (p) set('scanConditions', withIds(p.conditions)); }}>
          <option value="">Preset scans…</option>
          {SCAN_PRESETS.map((p) => <option key={p.name}>{p.name}</option>)}
        </select>
        <button onClick={() => setWizard(true)} className={`${btnCls} bg-accent text-white hover:bg-blue-500`}><Wand2 size={12} /> Condition Wizard</button>
        <span className="ml-auto font-mono text-2xs text-ink-400">{shown.length} / {rows.length} pass</span>
      </div>
      {scanConditions.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 border-b border-ink-800 px-2 py-1">
          {scanConditions.map((c) => (
            <span key={c.id} className="flex items-center gap-1 rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-2xs text-blue-200">
              {describe(c)}
              <button onClick={() => set('scanConditions', scanConditions.filter((x) => x.id !== c.id))} aria-label="Remove condition"><X size={10} /></button>
            </span>
          ))}
          <button className="ml-1 flex items-center gap-1 text-2xs text-ink-400 hover:text-ink-100" onClick={() => {
            const name = prompt('Name this scan', `Scan ${savedScans.length + 1}`);
            if (name) set('savedScans', [...savedScans, { name, conditions: scanConditions }]);
          }}><Save size={11} /> Save</button>
          <button className="text-2xs text-ink-400 hover:text-down" onClick={() => set('scanConditions', [])}>Clear</button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full">
          <thead className="sticky top-0 z-10 bg-ink-950 text-2xs uppercase text-ink-500">
            <tr>
              {COLS.map((c) => (
                <th key={c.key} onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? (-s.dir as 1 | -1) : c.num ? -1 : 1 }))}
                  className={`cursor-pointer select-none whitespace-nowrap px-2 py-1.5 font-medium hover:text-ink-100 ${c.num ? 'text-right' : 'text-left'}`}>
                  {c.label}{sort.key === c.key && (sort.dir === 1 ? <ArrowUp size={10} className="ml-0.5 inline" /> : <ArrowDown size={10} className="ml-0.5 inline" />)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono">
            {shown.map((r) => (
              <tr key={r.symbol} onClick={() => setSymbol(r.symbol)} className={`cursor-pointer border-t border-ink-800/60 ${r.symbol === symbol ? 'bg-accent/15' : 'hover:bg-ink-800'}`}>
                <td className="px-2 py-1 font-sans font-semibold text-ink-100">{r.symbol}</td>
                <td className="max-w-[160px] truncate px-2 py-1 font-sans text-ink-300">{r.name}</td>
                <td className="px-2 py-1 font-sans text-ink-400">{r.sector}</td>
                <td className="px-2 py-1 text-right">{r.price.toFixed(2)}</td>
                <td className={`px-2 py-1 text-right ${tone(r.changePct)}`}>{pct(r.changePct)}</td>
                <td className="px-2 py-1 text-right text-ink-300">{compactNum(r.volume)}</td>
                <td className={`px-2 py-1 text-right ${r.rsi14 !== null && r.rsi14 > 70 ? 'text-down' : r.rsi14 !== null && r.rsi14 < 30 ? 'text-up' : ''}`}>{r.rsi14?.toFixed(1) ?? '—'}</td>
                <td className={`px-2 py-1 text-right ${tone(r.macdHist ?? 0)}`}>{r.macdHist?.toFixed(2) ?? '—'}</td>
                <td className="px-2 py-1 text-right text-ink-300">${compactNum(r.marketCapB * 1e9)}</td>
                <td className={`px-2 py-1 text-right ${tone(r.epsGrowth)}`}>{r.epsGrowth.toFixed(1)}</td>
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={COLS.length} className="p-6 text-center font-sans text-ink-500">No symbols pass the current conditions.</td></tr>}
          </tbody>
        </table>
      </div>
      <AnimatePresence>{wizard && <ConditionWizard onClose={() => setWizard(false)} onAdd={(c) => set('scanConditions', [...scanConditions, c])} />}</AnimatePresence>
    </div>
  );
}

const METRICS = Object.keys(METRIC_LABELS) as Metric[];
const OPS: { id: Operator; label: string; hint: string }[] = [
  { id: '>', label: 'is above', hint: 'True on any bar where the value is greater' },
  { id: '<', label: 'is below', hint: 'True on any bar where the value is less' },
  { id: 'crossesAbove', label: 'crosses above', hint: 'True only on the bar where it moves from below to above' },
  { id: 'crossesBelow', label: 'crosses below', hint: 'True only on the bar where it moves from above to below' },
];
const STEPS = ['Indicator', 'Comparison', 'Target', 'Flex (over time)', 'Review'];

function ConditionWizard({ onClose, onAdd }: { onClose: () => void; onAdd: (c: Condition) => void }) {
  const [step, setStep] = useState(0);
  const [left, setLeft] = useState<Metric>('rsi14');
  const [op, setOp] = useState<Operator>('crossesAbove');
  const [rightKind, setRightKind] = useState<'value' | 'metric'>('value');
  const [value, setValue] = useState(30);
  const [rightMetric, setRightMetric] = useState<Metric>('sma50');
  const [within, setWithin] = useState(5);
  const [atLeast, setAtLeast] = useState(1);
  const cond: Condition = {
    id: newConditionId(), left, op,
    right: rightKind === 'value' ? { kind: 'value', value } : { kind: 'metric', metric: rightMetric },
    flex: within > 1 ? { atLeast: Math.min(atLeast, within), within } : undefined,
  };

  return (
    <motion.div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      <motion.div className="w-[480px] max-w-[95vw] rounded-lg border border-ink-700 bg-ink-850 shadow-2xl" initial={{ y: 20, scale: 0.97 }} animate={{ y: 0, scale: 1 }} exit={{ y: 20, scale: 0.97 }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-2.5">
          <Wand2 size={14} className="text-accent" /><span className="font-semibold">Condition Wizard</span>
          <button className="ml-auto text-ink-400 hover:text-ink-100" onClick={onClose} aria-label="Close"><X size={14} /></button>
        </div>
        <div className="flex gap-1 px-4 pt-3">
          {STEPS.map((s, i) => (
            <button key={s} onClick={() => setStep(i)} className="flex-1 text-left">
              <div className={`h-1 rounded ${i <= step ? 'bg-accent' : 'bg-ink-700'}`} />
              <div className={`mt-1 text-2xs ${i === step ? 'text-ink-100' : 'text-ink-500'}`}>{i + 1}. {s}</div>
            </button>
          ))}
        </div>
        <div className="min-h-[180px] p-4 text-xs">
          {step === 0 && (
            <Choice title="Which value do you want to test?">
              {METRICS.map((m) => <Pill key={m} on={left === m} onClick={() => setLeft(m)}>{METRIC_LABELS[m]}</Pill>)}
            </Choice>
          )}
          {step === 1 && (
            <Choice title={`${METRIC_LABELS[left]} …`}>
              {OPS.map((o) => (
                <button key={o.id} onClick={() => setOp(o.id)} className={`w-full rounded border p-2 text-left ${op === o.id ? 'border-accent bg-accent/10' : 'border-ink-700 hover:border-ink-500'}`}>
                  <div className="font-medium">{o.label}</div><div className="text-2xs text-ink-500">{o.hint}</div>
                </button>
              ))}
            </Choice>
          )}
          {step === 2 && (
            <Choice title="Compare against">
              <div className="mb-2 flex gap-2">
                <Pill on={rightKind === 'value'} onClick={() => setRightKind('value')}>A fixed value</Pill>
                <Pill on={rightKind === 'metric'} onClick={() => setRightKind('metric')}>Another indicator</Pill>
              </div>
              {rightKind === 'value'
                ? <input type="number" className={`${inputCls} w-32`} value={value} onChange={(e) => setValue(+e.target.value)} />
                : <div className="flex flex-wrap gap-1">{METRICS.filter((m) => m !== left).map((m) => <Pill key={m} on={rightMetric === m} onClick={() => setRightMetric(m)}>{METRIC_LABELS[m]}</Pill>)}</div>}
            </Choice>
          )}
          {step === 3 && (
            <Choice title="Flex: how often must it be true?">
              <div className="flex items-center gap-2">
                At least <input type="number" min={1} max={within} className={`${inputCls} w-14`} value={atLeast} onChange={(e) => setAtLeast(Math.max(1, +e.target.value))} />
                of the last <input type="number" min={1} max={100} className={`${inputCls} w-14`} value={within} onChange={(e) => setWithin(Math.max(1, +e.target.value))} /> bars
              </div>
              <p className="mt-2 text-2xs text-ink-500">Use 1 of 1 for "true on the latest bar". Flex lets a condition hold most of the time, e.g. price above SMA 50 on 8 of the last 10 bars.</p>
            </Choice>
          )}
          {step === 4 && (
            <Choice title="Review">
              <div className="rounded border border-accent/40 bg-accent/10 p-3 font-medium text-blue-100">{describe(cond)}</div>
            </Choice>
          )}
        </div>
        <div className="flex justify-between border-t border-ink-700 px-4 py-2.5">
          <button disabled={step === 0} onClick={() => setStep(step - 1)} className={`${btnCls} text-ink-300 hover:bg-ink-700`}><ChevronLeft size={12} /> Back</button>
          {step < STEPS.length - 1
            ? <button onClick={() => setStep(step + 1)} className={`${btnCls} bg-ink-700 hover:bg-ink-600`}>Next <ChevronRight size={12} /></button>
            : <button onClick={() => { onAdd(cond); onClose(); }} className={`${btnCls} bg-accent text-white hover:bg-blue-500`}><Plus size={12} /> Add condition</button>}
        </div>
      </motion.div>
    </motion.div>
  );
}

function Choice({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><div className="mb-2 text-ink-300">{title}</div><div className="flex flex-wrap gap-1.5">{children}</div></div>;
}
function Pill({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button onClick={onClick} className={`rounded-full border px-2.5 py-1 text-2xs ${on ? 'border-accent bg-accent/15 text-blue-100' : 'border-ink-700 text-ink-300 hover:border-ink-500'}`}>{children}</button>;
}
