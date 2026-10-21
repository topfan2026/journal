import { Eraser, MousePointer2, Minus, Ruler, Spline, TrendingUp } from 'lucide-react';
import { useWorkspace, type DrawTool } from '../store/workspace';

const TOOLS: { id: DrawTool; icon: typeof Minus; label: string }[] = [
  { id: 'cursor', icon: MousePointer2, label: 'Cursor (drag order lines, right-click to trade)' },
  { id: 'trend', icon: TrendingUp, label: 'Trendline — 2 clicks' },
  { id: 'channel', icon: Spline, label: 'Price channel — 3 clicks' },
  { id: 'hline', icon: Minus, label: 'Horizontal line — 1 click' },
  { id: 'measure', icon: Ruler, label: 'Measure — 2 clicks' },
];

export function DrawToolbar() {
  const { tool, set, symbol, clearDrawings } = useWorkspace();
  return (
    <div className="flex w-9 shrink-0 flex-col items-center gap-0.5 border-r border-ink-800 bg-ink-950 py-1">
      {TOOLS.map(({ id, icon: Icon, label }) => (
        <button key={id} title={label} onClick={() => set('tool', id)} className={`flex h-7 w-7 items-center justify-center rounded ${tool === id ? 'bg-accent text-white' : 'text-ink-400 hover:bg-ink-800 hover:text-ink-100'}`}>
          <Icon size={15} />
        </button>
      ))}
      <div className="my-1 h-px w-5 bg-ink-700" />
      <button title="Clear drawings" onClick={() => clearDrawings(symbol)} className="flex h-7 w-7 items-center justify-center rounded text-ink-400 hover:bg-ink-800 hover:text-down"><Eraser size={15} /></button>
    </div>
  );
}
