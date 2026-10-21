import { useState } from 'react';
import { Briefcase, Layers, NotebookPen, Radar, Receipt } from 'lucide-react';
import { useWorkspace } from '../store/workspace';
import { UNIVERSE } from '../data/universe';
import { PriceChart } from './PriceChart';
import { Sidebar } from './Sidebar';
import { DrawToolbar } from './DrawToolbar';
import { Resizer } from './Resizer';
import { TradeTicket } from './TradeTicket';
import { OptionsPanel } from './OptionsPanel';
import { JournalPanel } from './JournalPanel';
import { ScannerPanel } from './ScannerPanel';
import { OrdersPanel } from './OrdersPanel';
import { Tabs } from './ui';

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function Workspace() {
  const { layout, sizes, set, symbol } = useWorkspace();
  const [right, setRight] = useState<'trade' | 'options' | 'journal'>('trade');
  const [bottom, setBottom] = useState<'scan' | 'orders'>('scan');
  const resize = (k: keyof typeof sizes, d: number, lo: number, hi: number) => set('sizes', { ...sizes, [k]: clamp(sizes[k] + d, lo, hi) });
  const bottomH = layout === 'scanner' ? Math.max(sizes.bottom, 420) : sizes.bottom;

  return (
    <div className="flex min-h-0 flex-1">
      <div style={{ width: sizes.left }} className="hidden shrink-0 md:block"><Sidebar /></div>
      <div className="hidden md:block"><Resizer axis="x" onDelta={(d) => resize('left', d, 180, 420)} /></div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1">
          <DrawToolbar />
          <div className="min-w-0 flex-1">
            {layout === 'quad' ? <QuadCharts /> : <PriceChart key={symbol} symbol={symbol} />}
          </div>
        </div>
        <Resizer axis="y" onDelta={(d) => resize('bottom', -d, 120, 640)} />
        <div style={{ height: bottomH }} className="relative flex shrink-0 flex-col bg-ink-900">
          <Tabs value={bottom} onChange={setBottom} items={[
            { id: 'scan', label: <><Radar size={12} /> EasyScan</> },
            { id: 'orders', label: <><Receipt size={12} /> Orders &amp; Positions</> },
          ]} />
          <div className="relative min-h-0 flex-1">{bottom === 'scan' ? <ScannerPanel /> : <OrdersPanel />}</div>
        </div>
      </div>

      <div className="hidden lg:block"><Resizer axis="x" onDelta={(d) => resize('right', -d, 300, 560)} /></div>
      <div style={{ width: sizes.right }} className="hidden shrink-0 flex-col bg-ink-900 lg:flex">
        <Tabs value={right} onChange={setRight} items={[
          { id: 'trade', label: <><Briefcase size={12} /> Trade</> },
          { id: 'options', label: <><Layers size={12} /> Options</> },
          { id: 'journal', label: <><NotebookPen size={12} /> Journal</> },
        ]} />
        <div className="min-h-0 flex-1 overflow-y-auto">
          {right === 'trade' && <TradeTicket />}
          {right === 'options' && <OptionsPanel />}
          {right === 'journal' && <JournalPanel />}
        </div>
      </div>
    </div>
  );
}

function QuadCharts() {
  const { quadSymbols, set, setSymbol } = useWorkspace();
  return (
    <div className="grid h-full grid-cols-2 grid-rows-2 gap-px bg-ink-800">
      {quadSymbols.map((s, i) => (
        <div key={i} className="relative min-h-0" onDoubleClick={() => { setSymbol(s); set('layout', 'trader'); }}>
          <select
            className="absolute right-20 top-1 z-20 rounded border border-ink-700 bg-ink-950 px-1 text-2xs"
            value={s}
            onChange={(e) => set('quadSymbols', quadSymbols.map((x, j) => (j === i ? e.target.value : x)))}
          >
            {UNIVERSE.map((u) => <option key={u.symbol}>{u.symbol}</option>)}
          </select>
          <PriceChart key={s} symbol={s} compact />
        </div>
      ))}
    </div>
  );
}
