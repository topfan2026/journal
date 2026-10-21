import { useRef, type ReactNode } from 'react';
import { useWorkspace } from '../store/workspace';

/**
 * Two panes with a draggable divider. The first pane's share (0–1) is saved per `id`,
 * so layouts survive restarts and scale with the window.
 */
export function Split({ id, dir, initial, children }: { id: string; dir: 'row' | 'col'; initial: number; children: [ReactNode, ReactNode] }) {
  const frac = useWorkspace((s) => s.splits[id]) ?? initial;
  const ref = useRef<HTMLDivElement>(null);
  const row = dir === 'row';

  const onDown = (e: React.PointerEvent) => {
    e.preventDefault();
    const box = ref.current!.getBoundingClientRect();
    const move = (ev: PointerEvent) => {
      const f = row ? (ev.clientX - box.left) / box.width : (ev.clientY - box.top) / box.height;
      const splits = useWorkspace.getState().splits;
      useWorkspace.getState().set('splits', { ...splits, [id]: Math.min(0.9, Math.max(0.1, f)) });
    };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); document.body.style.cursor = ''; };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    document.body.style.cursor = row ? 'col-resize' : 'row-resize';
  };

  return (
    <div ref={ref} className={`flex h-full w-full min-h-0 min-w-0 ${row ? 'flex-row' : 'flex-col'}`}>
      <div className="min-h-0 min-w-0 overflow-hidden" style={{ flex: `${frac} 1 0` }}>{children[0]}</div>
      <div onPointerDown={onDown} className={`shrink-0 bg-ink-800 hover:bg-accent ${row ? 'w-1 cursor-col-resize' : 'h-1 cursor-row-resize'}`} />
      <div className="min-h-0 min-w-0 overflow-hidden" style={{ flex: `${1 - frac} 1 0` }}>{children[1]}</div>
    </div>
  );
}
