import { useEffect, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { useMarket, lastPrice } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { buildBracket } from '../lib/paper';
import { usd } from '../lib/format';
import { Field, btnCls, inputCls } from './ui';

/** Order entry with a multiple-exit (bracket) manager: target, stop and trailing stop share an OCA group. */
export function TradeTicket() {
  const symbol = useWorkspace((s) => s.symbol);
  const mode = useWorkspace((s) => s.mode);
  const place = useWorkspace((s) => s.placeOrders);
  const toast = useWorkspace((s) => s.toast);
  const onPrice = useWorkspace((s) => s.onPrice);
  const last = useMarket((s) => lastPrice(s.bars[symbol]));

  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY');
  const [qty, setQty] = useState(100);
  const [entryType, setEntryType] = useState<'MKT' | 'LMT' | 'STP'>('LMT');
  const [entry, setEntry] = useState('');
  const [useTarget, setUseTarget] = useState(true);
  const [useStop, setUseStop] = useState(true);
  const [useTrail, setUseTrail] = useState(false);
  const [targetPct, setTargetPct] = useState(4);
  const [stopPct, setStopPct] = useState(2);
  const [trail, setTrail] = useState(1.5);

  useEffect(() => { if (last) setEntry(last.toFixed(2)); }, [symbol]); // eslint-disable-line react-hooks/exhaustive-deps

  const ref = entryType === 'MKT' ? last : Number(entry) || last;
  const dir = side === 'BUY' ? 1 : -1;
  const target = +(ref * (1 + (dir * targetPct) / 100)).toFixed(2);
  const stop = +(ref * (1 - (dir * stopPct) / 100)).toFixed(2);
  const risk = useStop ? Math.abs(ref - stop) * qty : useTrail ? trail * qty : NaN;
  const reward = useTarget ? Math.abs(target - ref) * qty : NaN;

  const submit = () => {
    if (mode === 'live') { toast('Live account is read-only in this app — switch to Paper to trade.', 'down'); return; }
    const orders = buildBracket({
      symbol, side, qty, entryType, entryPrice: entryType === 'MKT' ? undefined : ref,
      target: useTarget ? target : undefined, stop: useStop ? stop : undefined, trail: useTrail ? trail : undefined,
    });
    place(orders);
    toast(`${side} ${qty} ${symbol} ${entryType}${entryType !== 'MKT' ? ` @ ${ref.toFixed(2)}` : ''} with ${orders.length - 1} OCA exit(s)`, 'info');
    if (entryType === 'MKT') onPrice(symbol, last);
  };

  return (
    <div className="space-y-3 p-3 text-xs">
      {mode === 'live' && (
        <div className="flex gap-2 rounded border border-warn/40 bg-warn/10 p-2 text-2xs text-warn">
          <ShieldAlert size={14} className="shrink-0" />
          Live mode shows your IBKR account read-only. Order routing to a real account is deliberately disabled — practice in Paper mode.
        </div>
      )}
      <div className="grid grid-cols-2 gap-1 rounded border border-ink-700 p-0.5">
        {(['BUY', 'SELL'] as const).map((s) => (
          <button key={s} onClick={() => setSide(s)} className={`rounded py-1.5 font-semibold ${side === s ? (s === 'BUY' ? 'bg-up text-ink-950' : 'bg-down text-white') : 'text-ink-400'}`}>{s}</button>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Qty"><input type="number" min={1} className={inputCls} value={qty} onChange={(e) => setQty(Math.max(1, +e.target.value))} /></Field>
        <Field label="Type">
          <select className={inputCls} value={entryType} onChange={(e) => setEntryType(e.target.value as typeof entryType)}>
            <option value="MKT">Market</option><option value="LMT">Limit</option><option value="STP">Stop</option>
          </select>
        </Field>
        <Field label="Price"><input disabled={entryType === 'MKT'} className={inputCls} value={entryType === 'MKT' ? last.toFixed(2) : entry} onChange={(e) => setEntry(e.target.value)} /></Field>
      </div>

      <div className="rounded border border-ink-800">
        <div className="border-b border-ink-800 px-2 py-1.5 text-2xs font-semibold uppercase tracking-wide text-ink-400">Exit strategy · One-Cancels-All</div>
        <ExitRow on={useTarget} setOn={setUseTarget} label="Profit target" color="text-up">
          <PctInput value={targetPct} onChange={setTargetPct} /> <span className="font-mono text-ink-300">{target.toFixed(2)}</span>
        </ExitRow>
        <ExitRow on={useStop} setOn={setUseStop} label="Stop loss" color="text-down">
          <PctInput value={stopPct} onChange={setStopPct} /> <span className="font-mono text-ink-300">{stop.toFixed(2)}</span>
        </ExitRow>
        <ExitRow on={useTrail} setOn={setUseTrail} label="Trailing stop" color="text-warn">
          <span className="text-ink-500">$</span>
          <input type="number" step={0.25} min={0.01} className={`${inputCls} h-6 w-16`} value={trail} onChange={(e) => setTrail(Math.max(0.01, +e.target.value))} />
        </ExitRow>
      </div>

      <div className="grid grid-cols-3 gap-2 font-mono text-2xs">
        <div className="rounded bg-ink-950 p-2"><div className="text-ink-500">Notional</div>{usd(ref * qty, 0)}</div>
        <div className="rounded bg-ink-950 p-2"><div className="text-ink-500">Risk</div><span className="text-down">{isNaN(risk) ? '∞' : usd(risk, 0)}</span></div>
        <div className="rounded bg-ink-950 p-2"><div className="text-ink-500">R:R</div>{!isNaN(risk) && !isNaN(reward) ? (reward / risk).toFixed(2) : '—'}</div>
      </div>

      <button onClick={submit} className={`${btnCls} h-9 w-full text-sm ${side === 'BUY' ? 'bg-up text-ink-950 hover:bg-green-400' : 'bg-down text-white hover:bg-red-400'}`}>
        {side === 'BUY' ? 'Buy' : 'Sell'} {qty} {symbol} {mode === 'paper' ? '(Paper)' : ''}
      </button>
      <p className="text-2xs text-ink-500">Tip: right-click the chart to place a limit/stop at any price, then drag the order line to adjust it.</p>
    </div>
  );
}

function ExitRow({ on, setOn, label, color, children }: { on: boolean; setOn: (b: boolean) => void; label: string; color: string; children: React.ReactNode }) {
  return (
    <label className={`flex items-center gap-2 px-2 py-1.5 ${on ? '' : 'opacity-50'}`}>
      <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} className="accent-blue-500" />
      <span className={`w-24 ${color}`}>{label}</span>
      <span className="ml-auto flex items-center gap-2">{children}</span>
    </label>
  );
}

function PctInput({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <span className="flex items-center gap-1">
      <input type="number" step={0.5} min={0.1} className={`${inputCls} h-6 w-14`} value={value} onChange={(e) => onChange(Math.max(0.1, +e.target.value))} />
      <span className="text-ink-500">%</span>
    </span>
  );
}
