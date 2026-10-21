import { useEffect, useState } from 'react';
import { BarChart3, Cable, FlaskConical, Home, Landmark, Search } from 'lucide-react';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { UNIVERSE } from '../data/universe';
import { equity } from '../lib/paper';
import { usd } from '../lib/format';

export function TopBar({ onHome }: { onHome: () => void }) {
  const { setSymbol, mode, set, toast, paper } = useWorkspace();
  const { source, setSource, checkIbkr, ibkr, ensure, bars } = useMarket();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const matches = q ? UNIVERSE.filter((u) => u.symbol.startsWith(q.toUpperCase()) || u.name.toLowerCase().includes(q.toLowerCase())).slice(0, 8) : [];

  useEffect(() => { checkIbkr(); }, [checkIbkr]);

  const go = (s: string) => { ensure(s); setSymbol(s); setQ(''); setOpen(false); };

  const toggleSource = async () => {
    if (source === 'ibkr') { setSource('mock'); toast('Switched to simulated market data'); return; }
    const st = await checkIbkr();
    if (!st.authenticated) { toast(st.reachable ? 'IBKR gateway found but not logged in — log in at https://localhost:5000' : 'IBKR bridge not reachable — see README', 'down'); return; }
    setSource('ibkr');
    toast('Streaming live data from Interactive Brokers', 'up');
  };
  const toggleMode = async () => {
    if (mode === 'live') { set('mode', 'paper'); return; }
    const st = await checkIbkr();
    if (!st.authenticated) { toast('Connect IBKR first to view your live account', 'down'); return; }
    set('mode', 'live');
  };

  const prices = Object.fromEntries(Object.entries(bars).map(([s, b]) => [s, b[b.length - 1]?.close ?? 0]));
  const dot = ibkr?.authenticated ? 'bg-up' : ibkr?.reachable ? 'bg-warn' : 'bg-ink-500';

  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-ink-800 bg-ink-950 px-3">
      <button onClick={onHome} className="flex items-center gap-2 font-semibold tracking-tight" title="Back to overview">
        <span className="flex h-6 w-6 items-center justify-center rounded bg-accent"><BarChart3 size={14} /></span>
        <span className="hidden sm:inline">ChartDesk</span>
      </button>
      <button onClick={onHome} className="text-ink-500 hover:text-ink-100 sm:hidden" aria-label="Home"><Home size={15} /></button>

      <div className="relative">
        <Search size={13} className="absolute left-2 top-2 text-ink-500" />
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onKeyDown={(e) => { if (e.key === 'Enter' && q.trim()) go(matches[0]?.symbol ?? q.trim().toUpperCase()); }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Symbol…"
          className="h-7 w-40 rounded border border-ink-700 bg-ink-900 pl-7 pr-2 text-xs uppercase outline-none placeholder:normal-case focus:border-accent sm:w-56"
        />
        {open && matches.length > 0 && (
          <div className="absolute left-0 top-8 z-50 w-72 rounded border border-ink-700 bg-ink-850 py-1 shadow-xl">
            {matches.map((m) => (
              <button key={m.symbol} onMouseDown={() => go(m.symbol)} className="flex w-full items-center gap-2 px-3 py-1 text-left text-xs hover:bg-ink-700">
                <b className="w-12">{m.symbol}</b><span className="truncate text-ink-400">{m.name}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="ml-auto flex items-center gap-2 text-xs">
        <button onClick={toggleSource} className="flex h-7 items-center gap-1.5 rounded border border-ink-700 px-2 hover:border-ink-500" title={ibkr?.message ?? ''}>
          <span className={`h-2 w-2 rounded-full ${source === 'ibkr' ? 'bg-up animate-pulse' : dot}`} />
          <Cable size={13} />
          <span className="hidden md:inline">{source === 'ibkr' ? 'IBKR live data' : 'Simulated data'}</span>
        </button>
        <div className="flex h-7 items-center rounded border border-ink-700 p-0.5">
          <button onClick={() => mode === 'live' && toggleMode()} className={`flex h-full items-center gap-1 rounded px-2 ${mode === 'paper' ? 'bg-warn/20 text-warn' : 'text-ink-400'}`}><FlaskConical size={12} /> Paper</button>
          <button onClick={() => mode === 'paper' && toggleMode()} className={`flex h-full items-center gap-1 rounded px-2 ${mode === 'live' ? 'bg-up/20 text-up' : 'text-ink-400'}`}><Landmark size={12} /> Live</button>
        </div>
        {mode === 'paper' && <span className="hidden font-mono text-ink-300 lg:inline">{usd(equity(paper, prices), 0)}</span>}
      </div>
    </header>
  );
}
