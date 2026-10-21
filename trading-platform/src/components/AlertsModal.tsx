import { useState } from 'react';
import { motion } from 'framer-motion';
import { Bell, Trash2, X } from 'lucide-react';
import { useMarket, lastPrice } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { btnCls, inputCls } from './ui';

export function AlertsModal({ onClose }: { onClose: () => void }) {
  const { alerts, addAlert, removeAlert, symbol, setSymbol, set } = useWorkspace();
  const bars = useMarket((s) => s.bars);
  const last = lastPrice(bars[symbol]);
  const [price, setPrice] = useState(() => (last * 1.02).toFixed(2));

  return (
    <motion.div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-24" initial={{ opacity: 0 }} animate={{ opacity: 1 }} onClick={onClose}>
      <motion.div initial={{ y: -10 }} animate={{ y: 0 }} className="w-[460px] max-w-[95vw] rounded-lg border border-ink-700 bg-ink-850 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-2.5 text-sm">
          <Bell size={14} className="text-yellow-300" /><span className="font-semibold">Price alerts</span>
          <button className="ml-auto text-ink-400 hover:text-ink-100" onClick={onClose} aria-label="Close"><X size={14} /></button>
        </div>
        <form className="flex items-end gap-2 border-b border-ink-700 p-4 text-xs" onSubmit={(e) => { e.preventDefault(); if (+price > 0) addAlert(symbol, +price, last); }}>
          <div className="flex-1">
            <div className="mb-1 text-2xs uppercase text-ink-500">New alert for {symbol} (last {last.toFixed(2)})</div>
            <input className={`${inputCls} w-full`} value={price} onChange={(e) => setPrice(e.target.value)} aria-label="Alert price" />
          </div>
          <button className={`${btnCls} bg-accent text-white hover:bg-blue-500`}>Add alert</button>
        </form>
        <div className="max-h-80 overflow-y-auto p-2 text-xs">
          {alerts.slice().reverse().map((a) => (
            <div key={a.id} className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-ink-800">
              <button className="font-semibold text-ink-100 hover:underline" onClick={() => { setSymbol(a.symbol); set('page', 'basic'); onClose(); }}>{a.symbol}</button>
              <span className="text-ink-300">{a.dir === 'above' ? 'rises to' : 'falls to'} <b className="font-mono">{a.price.toFixed(2)}</b></span>
              <span className={`ml-auto text-2xs ${a.triggeredAt ? 'text-yellow-300' : 'text-ink-500'}`}>{a.triggeredAt ? `Triggered ${new Date(a.triggeredAt).toLocaleTimeString()}` : `Last ${lastPrice(bars[a.symbol]).toFixed(2)}`}</span>
              <button className="text-ink-500 hover:text-down" onClick={() => removeAlert(a.id)} aria-label="Delete alert"><Trash2 size={12} /></button>
            </div>
          ))}
          {!alerts.length && <div className="p-4 text-center text-ink-500">No alerts. Right-click any price on a chart and choose "Set price alert".</div>}
        </div>
      </motion.div>
    </motion.div>
  );
}
