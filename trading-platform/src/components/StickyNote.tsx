import { useRef } from 'react';
import { StickyNote as NoteIcon, X } from 'lucide-react';
import { useWorkspace } from '../store/workspace';

/** A draggable sticky note pinned to the chart; text autosaves per ticker. */
export function StickyNote({ symbol }: { symbol: string }) {
  const note = useWorkspace((s) => s.notes[symbol]);
  const save = useWorkspace((s) => s.saveNote);
  const start = useRef<{ mx: number; my: number; x: number; y: number } | null>(null);
  if (!note?.visible || !note.text && note.updatedAt === 0) return null;

  const onDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    start.current = { mx: e.clientX, my: e.clientY, x: note.x, y: note.y };
  };
  const onMove = (e: React.PointerEvent) => {
    if (!start.current) return;
    save(symbol, { x: Math.max(0, start.current.x + e.clientX - start.current.mx), y: Math.max(0, start.current.y + e.clientY - start.current.my) });
  };

  return (
    <div
      className="absolute z-20 w-56 rounded-sm border border-yellow-500/40 bg-yellow-200/90 text-[11px] text-yellow-950 shadow-lg"
      style={{ left: note.x, top: note.y }}
      onPointerDownCapture={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.stopPropagation()}
    >
      <div className="flex cursor-move items-center gap-1 border-b border-yellow-600/30 px-2 py-0.5 font-semibold" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => (start.current = null)}>
        <NoteIcon size={11} /> {symbol} note
        <button className="ml-auto opacity-60 hover:opacity-100" onClick={() => save(symbol, { visible: false })} aria-label="Hide note"><X size={11} /></button>
      </div>
      <textarea
        className="h-20 w-full resize-none bg-transparent px-2 py-1 outline-none placeholder:text-yellow-800/60"
        placeholder="Type a note — saved automatically"
        value={note.text}
        onChange={(e) => save(symbol, { text: e.target.value })}
      />
    </div>
  );
}
