import { Pin, PinOff } from 'lucide-react';
import { useWorkspace } from '../store/workspace';

/** Per-ticker trading journal. The same note can be pinned to the chart as a sticky note. */
export function JournalPanel() {
  const { symbol, notes, saveNote, setSymbol } = useWorkspace();
  const note = notes[symbol];
  const others = Object.entries(notes).filter(([s, n]) => s !== symbol && n.text.trim()).sort((a, b) => b[1].updatedAt - a[1].updatedAt);

  return (
    <div className="flex h-full flex-col gap-2 p-3 text-xs">
      <div className="flex items-center gap-2">
        <span className="font-semibold">{symbol} journal</span>
        {note?.updatedAt ? <span className="text-2xs text-ink-500">saved {new Date(note.updatedAt).toLocaleTimeString()}</span> : null}
        <button
          onClick={() => saveNote(symbol, { visible: !(note?.visible ?? false) })}
          className={`ml-auto flex items-center gap-1 rounded px-2 py-1 text-2xs ${note?.visible ? 'bg-yellow-400/15 text-yellow-300' : 'text-ink-400 hover:text-ink-100'}`}
        >
          {note?.visible ? <PinOff size={11} /> : <Pin size={11} />} {note?.visible ? 'Unpin from chart' : 'Pin to chart'}
        </button>
      </div>
      <textarea
        className="min-h-[160px] flex-1 resize-none rounded border border-ink-700 bg-ink-950 p-2 leading-relaxed outline-none focus:border-accent"
        placeholder={`Thesis, entries, exits, lessons for ${symbol}… (autosaves)`}
        value={note?.text ?? ''}
        onChange={(e) => saveNote(symbol, { text: e.target.value, visible: note?.visible ?? true })}
      />
      {others.length > 0 && (
        <div className="max-h-48 overflow-y-auto">
          <div className="mb-1 text-2xs uppercase tracking-wide text-ink-500">Other notes</div>
          {others.map(([s, n]) => (
            <button key={s} onClick={() => setSymbol(s)} className="block w-full rounded px-2 py-1 text-left hover:bg-ink-800">
              <span className="font-semibold">{s}</span> <span className="text-2xs text-ink-500">{new Date(n.updatedAt).toLocaleDateString()}</span>
              <div className="truncate text-2xs text-ink-400">{n.text}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
