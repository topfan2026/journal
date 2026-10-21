import { useState } from 'react';
import { X } from 'lucide-react';
import { useWorkspace } from '../store/workspace';
import { orderId } from '../lib/paper';
import { usd } from '../lib/format';
import { inputCls } from './ui';

/** Small order ticket opened from the chart's Buy / Sell buttons. */
export function QuickOrder({ symbol, side, last, onClose }: { symbol: string; side: 'BUY' | 'SELL'; last: number; onClose: () => void }) {
  const { placeOrders, onPrice, toast, mode, set } = useWorkspace();
  const [qty, setQty] = useState(100);
  const [type, setType] = useState<'MKT' | 'LMT' | 'STP'>('MKT');
  const [price, setPrice] = useState(last.toFixed(2));
  const buy = side === 'BUY';

  const send = () => {
    if (mode === 'live') { toast('Live account is read-only in this app — switch to Paper to trade.', 'down'); return; }
    const px = type === 'MKT' ? undefined : +price;
    placeOrders([{ id: orderId(), symbol, side, type, qty, price: px, status: 'WORKING', createdAt: Date.now(), label: 'Ticket' }]);
    if (type === 'MKT') onPrice(symbol, last);
    else toast(`${side} ${type} ${qty} ${symbol} @ ${px?.toFixed(2)} working`);
    onClose();
  };

  return (
    <div className="absolute left-2 top-20 z-40 w-64 rounded border border-ink-700 bg-ink-850 p-3 text-xs shadow-2xl" onClick={(e) => e.stopPropagation()}>
      <div className="mb-2 flex items-center">
        <span className={`font-semibold ${buy ? 'text-up' : 'text-down'}`}>{side} {symbol}</span>
        <span className="ml-2 font-mono text-ink-400">{last.toFixed(2)}</span>
        <button className="ml-auto text-ink-500 hover:text-ink-100" onClick={onClose} aria-label="Close"><X size={13} /></button>
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        <input type="number" min={1} className={inputCls} value={qty} onChange={(e) => setQty(Math.max(1, +e.target.value))} aria-label="Quantity" />
        <select className={inputCls} value={type} onChange={(e) => setType(e.target.value as typeof type)} aria-label="Order type">
          <option value="MKT">Market</option><option value="LMT">Limit</option><option value="STP">Stop</option>
        </select>
        <input className={inputCls} disabled={type === 'MKT'} value={type === 'MKT' ? 'MKT' : price} onChange={(e) => setPrice(e.target.value)} aria-label="Price" />
      </div>
      <div className="mt-2 flex items-center justify-between font-mono text-2xs text-ink-400">
        <span>Est. {usd(qty * (type === 'MKT' ? last : +price || last), 0)}</span>
        <button className="font-sans text-accent hover:underline" onClick={() => { set('page', 'trading'); onClose(); }}>Bracket / exits…</button>
      </div>
      <button onClick={send} className={`mt-2 h-8 w-full rounded font-semibold ${buy ? 'bg-up text-ink-950 hover:bg-green-400' : 'bg-down text-white hover:bg-red-400'}`}>
        {side} {qty} {mode === 'paper' ? '· Paper' : ''}
      </button>
    </div>
  );
}
