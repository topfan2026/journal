import { useState } from 'react';
import { motion } from 'framer-motion';
import { Activity, Filter, LayoutGrid, List, Plus, Trash2 } from 'lucide-react';
import { useMarket } from '../store/market';
import { useWorkspace, type IndicatorKey, type LayoutPreset } from '../store/workspace';
import { WATCHLISTS } from '../data/universe';
import { SCAN_PRESETS, describe, withIds } from '../lib/scanner';
import { pct, tone } from '../lib/format';
import { inputCls } from './ui';

type Section = 'watchlists' | 'indicators' | 'conditions' | 'layouts';

const SECTIONS: { id: Section; icon: typeof List; label: string }[] = [
  { id: 'watchlists', icon: List, label: 'Watchlists' },
  { id: 'indicators', icon: Activity, label: 'Indicators' },
  { id: 'conditions', icon: Filter, label: 'Conditions' },
  { id: 'layouts', icon: LayoutGrid, label: 'Layouts' },
];

export function Sidebar() {
  const [section, setSection] = useState<Section>('watchlists');
  return (
    <div className="flex h-full">
      <nav className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-ink-800 bg-ink-950 py-2">
        {SECTIONS.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            title={label}
            onClick={() => setSection(id)}
            className={`relative flex h-9 w-9 items-center justify-center rounded ${section === id ? 'text-accent' : 'text-ink-500 hover:text-ink-100'}`}
          >
            {section === id && <motion.span layoutId="side-active" className="absolute inset-0 rounded bg-accent/10" />}
            <Icon size={17} />
          </button>
        ))}
      </nav>
      <div className="flex min-w-0 flex-1 flex-col bg-ink-900">
        <div className="flex h-8 shrink-0 items-center border-b border-ink-800 px-3 text-xs font-semibold uppercase tracking-wide text-ink-300">
          {SECTIONS.find((s) => s.id === section)!.label}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {section === 'watchlists' && <Watchlists />}
          {section === 'indicators' && <Indicators />}
          {section === 'conditions' && <Conditions />}
          {section === 'layouts' && <Layouts />}
        </div>
      </div>
    </div>
  );
}

function Watchlists() {
  const { watchlist, customWatchlist, symbol, setSymbol, set } = useWorkspace();
  const bars = useMarket((s) => s.bars);
  const prev = useMarket((s) => s.prevClose);
  const ensure = useMarket((s) => s.ensure);
  const [add, setAdd] = useState('');
  const lists = { ...WATCHLISTS, 'My List': customWatchlist };
  const symbols = lists[watchlist as keyof typeof lists] ?? [];

  return (
    <div>
      <div className="p-2">
        <select className={`${inputCls} w-full font-sans`} value={watchlist} onChange={(e) => set('watchlist', e.target.value)}>
          {Object.keys(lists).map((n) => <option key={n}>{n}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-[1fr_auto_auto] gap-x-2 px-3 pb-1 text-2xs uppercase text-ink-500">
        <span>Symbol</span><span className="text-right">Last</span><span className="w-14 text-right">Chg</span>
      </div>
      {symbols.map((s) => {
        const b = bars[s];
        const last = b?.[b.length - 1]?.close ?? 0;
        const chg = prev[s] ? ((last - prev[s]) / prev[s]) * 100 : 0;
        return (
          <div
            key={s}
            onClick={() => { ensure(s); setSymbol(s); }}
            className={`group grid cursor-pointer grid-cols-[1fr_auto_auto] items-center gap-x-2 px-3 py-1 font-mono text-xs ${s === symbol ? 'bg-accent/15 text-ink-100' : 'text-ink-300 hover:bg-ink-800'}`}
          >
            <span className="flex items-center gap-1 font-sans font-semibold">
              {s}
              {watchlist === 'My List' && (
                <button className="hidden text-ink-500 hover:text-down group-hover:inline" onClick={(e) => { e.stopPropagation(); set('customWatchlist', customWatchlist.filter((x) => x !== s)); }} aria-label={`Remove ${s}`}>
                  <Trash2 size={11} />
                </button>
              )}
            </span>
            <span className="text-right">{last ? last.toFixed(2) : '—'}</span>
            <span className={`w-14 text-right ${tone(chg)}`}>{pct(chg)}</span>
          </div>
        );
      })}
      {watchlist === 'My List' && (
        <form className="flex gap-1 p-2" onSubmit={(e) => { e.preventDefault(); const s = add.trim().toUpperCase(); if (s && !customWatchlist.includes(s)) { ensure(s); set('customWatchlist', [...customWatchlist, s]); } setAdd(''); }}>
          <input className={`${inputCls} min-w-0 flex-1`} placeholder="Add symbol" value={add} onChange={(e) => setAdd(e.target.value)} />
          <button className="rounded bg-ink-700 px-2 text-ink-100 hover:bg-ink-600" aria-label="Add"><Plus size={13} /></button>
        </form>
      )}
    </div>
  );
}

const INDICATORS: { key: IndicatorKey; label: string; color: string; group: string }[] = [
  { key: 'sma20', label: 'SMA 20', color: '#f59e0b', group: 'Overlays' },
  { key: 'sma50', label: 'SMA 50', color: '#3b82f6', group: 'Overlays' },
  { key: 'sma200', label: 'SMA 200', color: '#a855f7', group: 'Overlays' },
  { key: 'bbands', label: 'Bollinger Bands (20, 2)', color: '#64748b', group: 'Overlays' },
  { key: 'volume', label: 'Volume', color: '#22c55e', group: 'Overlays' },
  { key: 'rsi', label: 'RSI (14)', color: '#c084fc', group: 'Lower panes' },
  { key: 'macd', label: 'MACD (12, 26, 9)', color: '#38bdf8', group: 'Lower panes' },
];

function Indicators() {
  const { indicators, toggleIndicator, chartType, set } = useWorkspace();
  return (
    <div className="space-y-3 p-3 text-xs">
      <div className="flex rounded border border-ink-700 p-0.5">
        {(['candles', 'line'] as const).map((t) => (
          <button key={t} onClick={() => set('chartType', t)} className={`flex-1 rounded py-1 capitalize ${chartType === t ? 'bg-ink-700 text-ink-100' : 'text-ink-400'}`}>{t}</button>
        ))}
      </div>
      {['Overlays', 'Lower panes'].map((g) => (
        <div key={g}>
          <div className="mb-1 text-2xs uppercase tracking-wide text-ink-500">{g}</div>
          {INDICATORS.filter((i) => i.group === g).map((i) => (
            <label key={i.key} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 hover:bg-ink-800">
              <input type="checkbox" checked={indicators[i.key]} onChange={() => toggleIndicator(i.key)} className="accent-blue-500" />
              <span className="h-0.5 w-4" style={{ background: i.color }} />
              {i.label}
            </label>
          ))}
        </div>
      ))}
    </div>
  );
}

function Conditions() {
  const { scanConditions, savedScans, set } = useWorkspace();
  return (
    <div className="space-y-3 p-3 text-xs">
      <div>
        <div className="mb-1 text-2xs uppercase tracking-wide text-ink-500">Preset scans</div>
        {SCAN_PRESETS.map((p) => (
          <button key={p.name} onClick={() => set('scanConditions', withIds(p.conditions))} className="block w-full rounded px-2 py-1.5 text-left hover:bg-ink-800">
            <div className="font-medium text-ink-100">{p.name}</div>
            <div className="text-2xs text-ink-500">{p.description}</div>
          </button>
        ))}
      </div>
      {savedScans.length > 0 && (
        <div>
          <div className="mb-1 text-2xs uppercase tracking-wide text-ink-500">My conditions</div>
          {savedScans.map((s, i) => (
            <div key={i} className="group flex items-start rounded px-2 py-1.5 hover:bg-ink-800">
              <button className="flex-1 text-left" onClick={() => set('scanConditions', s.conditions)}>
                <div className="font-medium text-ink-100">{s.name}</div>
                <div className="text-2xs text-ink-500">{s.conditions.map(describe).join(' AND ')}</div>
              </button>
              <button className="hidden text-ink-500 hover:text-down group-hover:block" onClick={() => set('savedScans', savedScans.filter((_, j) => j !== i))} aria-label="Delete scan"><Trash2 size={12} /></button>
            </div>
          ))}
        </div>
      )}
      <div className="rounded border border-ink-800 bg-ink-950 p-2 text-2xs text-ink-400">
        Active: {scanConditions.length ? scanConditions.map(describe).join(' AND ') : 'none — open the EasyScan tab below to build one.'}
      </div>
    </div>
  );
}

const LAYOUTS: { id: LayoutPreset; name: string; desc: string; cells: string }[] = [
  { id: 'trader', name: 'Trader', desc: 'Chart, trade ticket, scanner', cells: 'grid-cols-[2fr_1fr] grid-rows-[2fr_1fr]' },
  { id: 'quad', name: 'Quad Charts', desc: 'Four linked charts', cells: 'grid-cols-2 grid-rows-2' },
  { id: 'scanner', name: 'Scan Focus', desc: 'Large scanner, compact chart', cells: 'grid-cols-[2fr_1fr] grid-rows-[1fr_2fr]' },
];

function Layouts() {
  const { layout, set } = useWorkspace();
  return (
    <div className="space-y-2 p-3 text-xs">
      {LAYOUTS.map((l) => (
        <button key={l.id} onClick={() => set('layout', l.id)} className={`flex w-full items-center gap-3 rounded border p-2 text-left ${layout === l.id ? 'border-accent bg-accent/10' : 'border-ink-800 hover:border-ink-600'}`}>
          <div className={`grid h-9 w-12 shrink-0 gap-0.5 ${l.cells}`}>
            {Array.from({ length: 4 }).map((_, i) => <span key={i} className="rounded-sm bg-ink-600" />)}
          </div>
          <div>
            <div className="font-medium text-ink-100">{l.name}</div>
            <div className="text-2xs text-ink-500">{l.desc}</div>
          </div>
        </button>
      ))}
      <p className="pt-2 text-2xs text-ink-500">Drag the dividers between panels to resize. Your layout, indicators, drawings and notes are saved in this browser.</p>
    </div>
  );
}
