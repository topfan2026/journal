import { useState } from 'react';
import { Briefcase, Layers } from 'lucide-react';
import { useWorkspace, type PageId } from '../store/workspace';
import { PriceChart } from './PriceChart';
import { DrawToolbar } from './DrawToolbar';
import { Split } from './Split';
import { WatchlistPanel } from './WatchlistPanel';
import { OptionChainPanel } from './OptionChainPanel';
import { NewsNotesPanel } from './NewsNotesPanel';
import { PositionsPanel } from './PositionsPanel';
import { OrdersTradesPanel } from './OrdersTradesPanel';
import { FundamentalsPanel } from './FundamentalsPanel';
import { ScannerPanel } from './ScannerPanel';
import { TradeTicket } from './TradeTicket';
import { OptionsPanel } from './OptionsPanel';
import { Tabs } from './ui';
import { StrategyPage } from './StrategyPage';

export const PAGES: { id: PageId; label: string }[] = [
  { id: 'basic', label: 'Basic' },
  { id: 'trading', label: 'Trading' },
  { id: 'scan', label: 'EasyScan' },
  { id: 'strategy', label: 'Strategy Tester' },
  { id: 'chart1', label: '1-Chart' },
  { id: 'tf4', label: '4-Timeframe' },
  { id: 'options', label: 'Options' },
  { id: 'fundamentals', label: 'Fundamentals' },
];

function ChartWindow() {
  const symbol = useWorkspace((s) => s.symbol);
  return (
    <div className="flex h-full">
      <DrawToolbar />
      <div className="min-w-0 flex-1"><PriceChart key={symbol} symbol={symbol} /></div>
    </div>
  );
}

const Bottom = ({ id }: { id: string }) => (
  <Split id={`${id}.bottom`} dir="row" initial={0.45}>
    <PositionsPanel />
    <OrdersTradesPanel />
  </Split>
);

function TradeSide() {
  const [tab, setTab] = useState<'trade' | 'options'>('trade');
  return (
    <div className="flex h-full flex-col bg-ink-900">
      <Tabs value={tab} onChange={setTab} items={[{ id: 'trade', label: <><Briefcase size={12} /> Order ticket</> }, { id: 'options', label: <><Layers size={12} /> Option strategy</> }]} />
      <div className="min-h-0 flex-1 overflow-y-auto">{tab === 'trade' ? <TradeTicket /> : <OptionsPanel />}</div>
    </div>
  );
}

function FourTimeframe() {
  const symbol = useWorkspace((s) => s.symbol);
  return (
    <Split id="tf4.main" dir="row" initial={0.8}>
      <div className="grid h-full grid-cols-2 grid-rows-2 gap-px bg-ink-800">
        {(['15m', '1h', 'D', 'W'] as const).map((tf) => (
          <div key={tf} className="min-h-0 min-w-0"><PriceChart key={`${symbol}-${tf}`} symbol={symbol} tf={tf} compact /></div>
        ))}
      </div>
      <WatchlistPanel />
    </Split>
  );
}

export function Page() {
  const page = useWorkspace((s) => s.page);
  switch (page) {
    case 'trading':
      return (
        <Split id="trading.main" dir="row" initial={0.72}>
          <Split id="trading.left" dir="col" initial={0.68}><ChartWindow /><Bottom id="trading" /></Split>
          <TradeSide />
        </Split>
      );
    case 'scan':
      return (
        <Split id="scan.main" dir="col" initial={0.45}>
          <Split id="scan.top" dir="row" initial={0.7}><ChartWindow /><WatchlistPanel /></Split>
          <div className="relative h-full bg-ink-900"><ScannerPanel /></div>
        </Split>
      );
    case 'strategy':
      return <StrategyPage />;
    case 'chart1':
      return <ChartWindow />;
    case 'tf4':
      return <FourTimeframe />;
    case 'options':
      return (
        <Split id="options.main" dir="row" initial={0.58}>
          <ChartWindow />
          <Split id="options.right" dir="col" initial={0.55}>
            <div className="h-full overflow-y-auto bg-ink-900"><OptionsPanel /></div>
            <OptionChainPanel />
          </Split>
        </Split>
      );
    case 'fundamentals':
      return (
        <Split id="fund.main" dir="row" initial={0.66}>
          <ChartWindow />
          <Split id="fund.right" dir="col" initial={0.62}><FundamentalsPanel /><NewsNotesPanel /></Split>
        </Split>
      );
    default:
      return (
        <Split id="basic.main" dir="row" initial={0.68}>
          <Split id="basic.left" dir="col" initial={0.74}><ChartWindow /><Bottom id="basic" /></Split>
          <Split id="basic.right" dir="col" initial={0.36}>
            <WatchlistPanel />
            <Split id="basic.right2" dir="col" initial={0.5}>
              <OptionChainPanel />
              <Split id="basic.right3" dir="row" initial={0.5}><WatchlistPanel fixed="favorites" /><NewsNotesPanel /></Split>
            </Split>
          </Split>
        </Split>
      );
  }
}

export function PageTabs() {
  const { page, set } = useWorkspace();
  return (
    <div className="flex h-6 shrink-0 items-stretch gap-px border-t border-ink-800 bg-ink-950 px-1 text-xs">
      {PAGES.map((p) => (
        <button key={p.id} onClick={() => set('page', p.id)}
          className={`px-3 ${page === p.id ? 'bg-ink-800 font-semibold text-ink-100 shadow-[inset_0_-2px_0_#3b82f6]' : 'text-ink-400 hover:text-ink-100'}`}>
          {p.label}
        </button>
      ))}
    </div>
  );
}
