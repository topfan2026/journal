import { useEffect, useState } from 'react';
import { Bell, BookOpen, Cable, ChevronDown, LineChart, List, Newspaper, Plus, Radar, Wallet } from 'lucide-react';
import { useMarket } from '../store/market';
import { useWorkspace, type PageId } from '../store/workspace';
import { dayPnl, equity } from '../lib/paper';
import { usd } from '../lib/format';
import { AlertsModal } from './AlertsModal';

/** Top toolbar (navigation) and the account strip below it. */
export function AppToolbar() {
  const { set, toast, mode, paper, alerts } = useWorkspace();
  const { source, setSource, checkIbkr, ibkr, bars } = useMarket();
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [acctOpen, setAcctOpen] = useState(false);
  const [now, setNow] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(id); }, []);
  useEffect(() => { checkIbkr(); }, [checkIbkr]);

  const go = (p: PageId) => set('page', p);
  const toggleSource = async () => {
    if (source === 'ibkr') { setSource('mock'); toast('Switched to simulated market data'); return; }
    const st = await checkIbkr();
    if (!st.authenticated) { toast(st.reachable ? 'IBKR gateway found but not logged in — use IBKR menu → Open IBKR Gateway Login' : 'IBKR gateway not running — start the Client Portal Gateway first', 'down'); return; }
    setSource('ibkr');
    toast('Streaming live data from Interactive Brokers', 'up');
  };
  const chooseMode = async (m: 'paper' | 'live') => {
    setAcctOpen(false);
    if (m === 'paper') { set('mode', 'paper'); return; }
    const st = await checkIbkr();
    if (!st.authenticated) { toast('Log in to the IBKR gateway first to view your live account', 'down'); return; }
    set('mode', 'live');
  };

  const prices = Object.fromEntries(Object.entries(bars).map(([s, b]) => [s, b[b.length - 1]?.close ?? 0]));
  const eq = equity(paper, prices);
  const longVal = Object.values(paper.positions).reduce((a, p) => a + (p.qty > 0 ? p.qty * prices[p.symbol] : 0), 0);
  const dayPl = Object.values(paper.positions).reduce((a, p) => a + (dayPnl(p, prices[p.symbol], useMarket.getState().prevClose[p.symbol]) ?? 0), 0);
  const activeAlerts = alerts.filter((a) => !a.triggeredAt).length;
  const dot = ibkr?.authenticated ? 'bg-up' : ibkr?.reachable ? 'bg-warn' : 'bg-ink-500';

  const Btn = ({ icon: Icon, label, onClick, badge }: { icon: typeof Plus; label: string; onClick: () => void; badge?: number }) => (
    <button onClick={onClick} className="relative flex h-6 items-center gap-1 rounded px-2 text-ink-300 hover:bg-ink-800 hover:text-ink-100">
      <Icon size={13} /> {label}
      {!!badge && <span className="absolute -right-0.5 -top-0.5 rounded-full bg-yellow-400 px-1 text-[9px] font-bold leading-tight text-ink-950">{badge}</span>}
    </button>
  );

  return (
    <>
      <div className="flex h-8 shrink-0 items-center gap-0.5 border-b border-ink-800 bg-ink-950 px-2 text-xs">
        <Btn icon={Plus} label="New" onClick={() => go('chart1')} />
        <Btn icon={LineChart} label="Charts" onClick={() => go('basic')} />
        <Btn icon={List} label="WatchLists" onClick={() => go('basic')} />
        <Btn icon={Radar} label="EasyScan" onClick={() => go('scan')} />
        <Btn icon={Newspaper} label="News & Notes" onClick={() => go('basic')} />
        <Btn icon={Bell} label="Alerts" onClick={() => setAlertsOpen(true)} badge={activeAlerts} />
        <Btn icon={BookOpen} label="Fundamentals" onClick={() => go('fundamentals')} />
        <Btn icon={Wallet} label="Trading" onClick={() => go('trading')} />

        <div className="relative mx-auto">
          <button onClick={() => setAcctOpen(!acctOpen)} className={`flex items-center gap-1 rounded px-2 py-0.5 font-semibold ${mode === 'paper' ? 'text-warn' : 'text-up'}`}>
            {mode === 'paper' ? 'Paper: Practice' : `Live: IBKR`} <ChevronDown size={11} />
          </button>
          {acctOpen && (
            <div className="absolute left-1/2 top-7 z-50 w-52 -translate-x-1/2 rounded border border-ink-700 bg-ink-850 py-1 shadow-xl">
              <button onClick={() => chooseMode('paper')} className="block w-full px-3 py-1.5 text-left hover:bg-ink-700">Paper: Practice <span className="text-2xs text-ink-500">($100k simulated)</span></button>
              <button onClick={() => chooseMode('live')} className="block w-full px-3 py-1.5 text-left hover:bg-ink-700">Live: IBKR account <span className="text-2xs text-ink-500">(read-only)</span></button>
            </div>
          )}
        </div>

        <button onClick={toggleSource} className="flex h-6 items-center gap-1.5 rounded border border-ink-700 px-2 hover:border-ink-500" title={ibkr?.message ?? ''}>
          <span className={`h-2 w-2 rounded-full ${source === 'ibkr' ? 'animate-pulse bg-up' : dot}`} />
          <Cable size={12} /> {source === 'ibkr' ? 'IBKR live data' : 'Simulated data'}
        </button>
        <span className="ml-3 font-mono text-ink-400">{now.toLocaleTimeString()}</span>
      </div>
      <div className="flex h-6 shrink-0 items-center gap-4 border-b border-ink-800 bg-[#0b0e13] px-3 font-mono text-2xs text-ink-400">
        <span>Today <b className={dayPl >= 0 ? 'text-up' : 'text-down'}>{usd(dayPl, 0)}</b></span>
        <span>Lng <b className="text-ink-200">{usd(longVal, 0)}</b></span>
        <span>Cash <b className="text-ink-200">{usd(paper.cash, 0)}</b></span>
        <span>Acct Val <b className="text-ink-200">{usd(eq, 0)}</b></span>
        <span className="ml-auto">Simulated Buying Power <b className="text-ink-200">{usd(Math.max(0, eq * 2 - longVal), 0)}</b></span>
      </div>
      {alertsOpen && <AlertsModal onClose={() => setAlertsOpen(false)} />}
    </>
  );
}
