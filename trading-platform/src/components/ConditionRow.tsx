import { Trash2 } from 'lucide-react';
import { METRIC_LABELS, type Condition, type Metric, type Operator } from '../lib/scanner';

const METRICS = Object.keys(METRIC_LABELS) as Metric[];
const OPS: { id: Operator; label: string }[] = [
  { id: '>', label: 'is above' }, { id: '<', label: 'is below' },
  { id: 'crossesAbove', label: 'crosses above' }, { id: 'crossesBelow', label: 'crosses below' },
];
const sel = 'h-6 rounded border border-ink-700 bg-ink-950 px-1 text-2xs text-ink-100 outline-none focus:border-accent';

/** Inline editor for one rule: [metric] [operator] [value | metric] (N of last M bars). */
export function ConditionRow({ c, onChange, onDelete }: { c: Condition; onChange: (c: Condition) => void; onDelete: () => void }) {
  const within = c.flex?.within ?? 1;
  return (
    <div className="flex flex-wrap items-center gap-1 rounded border border-ink-800 bg-ink-950/60 p-1.5">
      <select className={sel} value={c.left} onChange={(e) => onChange({ ...c, left: e.target.value as Metric })}>
        {METRICS.map((m) => <option key={m} value={m}>{METRIC_LABELS[m]}</option>)}
      </select>
      <select className={sel} value={c.op} onChange={(e) => onChange({ ...c, op: e.target.value as Operator })}>
        {OPS.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
      <select className={sel} value={c.right.kind === 'value' ? '__value' : c.right.metric}
        onChange={(e) => onChange({ ...c, right: e.target.value === '__value' ? { kind: 'value', value: c.right.kind === 'value' ? c.right.value : 0 } : { kind: 'metric', metric: e.target.value as Metric } })}>
        <option value="__value">value…</option>
        {METRICS.map((m) => <option key={m} value={m}>{METRIC_LABELS[m]}</option>)}
      </select>
      {c.right.kind === 'value' && (
        <input type="number" className={`${sel} w-16`} value={c.right.value} onChange={(e) => onChange({ ...c, right: { kind: 'value', value: +e.target.value } })} aria-label="Value" />
      )}
      <span className="flex items-center gap-1 text-2xs text-ink-500" title="Flex: true on at least N of the last M bars">
        <input type="number" min={1} className={`${sel} w-9`} value={c.flex?.atLeast ?? 1} onChange={(e) => onChange({ ...c, flex: { atLeast: Math.max(1, +e.target.value), within } })} aria-label="At least" />
        of last
        <input type="number" min={1} className={`${sel} w-9`} value={within} onChange={(e) => onChange({ ...c, flex: { atLeast: Math.min(c.flex?.atLeast ?? 1, Math.max(1, +e.target.value)), within: Math.max(1, +e.target.value) } })} aria-label="Within bars" />
        bars
      </span>
      <button className="ml-auto text-ink-500 hover:text-down" onClick={onDelete} aria-label="Delete rule"><Trash2 size={12} /></button>
    </div>
  );
}
