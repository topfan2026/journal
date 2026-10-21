import { Pin, PinOff } from 'lucide-react';
import { useWorkspace } from '../store/workspace';
import { PanelHeader } from './ui';

/** News & Notes window: your notes for the current symbol (autosaved), plus recent notes on other symbols. */
export function NewsNotesPanel() {
  const { symbol, notes, saveNote, setSymbol } = useWorkspace();
  const note = notes[symbol];
  const others = Object.entries(notes).filter(([s, n]) => s !== symbol && n.text.trim()).sort((a, b) => b[1].updatedAt - a[1].updatedAt);

  return (
    <div className="flex h-full flex-col bg-[#0b0e13] text-xs">
      <PanelHeader>
        <span className="font-semibold text-ink-100">News &amp; Notes</span>
        <span className="text-ink-400">· {symbol}</span>
        <button
          onClick={() => saveNote(symbol, { visible: !(note?.visible ?? false) })}
          className={`ml-auto flex items-center gap-1 rounded px-1.5 text-2xs ${note?.visible ? 'text-yellow-300' : 'text-ink-400 hover:text-ink-100'}`}
          title="Show this note as a sticky note on the chart"
        >
          {note?.visible ? <PinOff size={10} /> : <Pin size={10} />} {note?.visible ? 'Unpin' : 'Pin to chart'}
        </button>
      </PanelHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-2 p-2">
        <textarea
          className="min-h-[70px] flex-1 resize-none rounded border border-ink-800 bg-ink-950 p-2 leading-relaxed outline-none focus:border-accent"
          placeholder={`Notes for ${symbol} — thesis, levels, lessons… (saved automatically)`}
          value={note?.text ?? ''}
          onChange={(e) => saveNote(symbol, { text: e.target.value })}
        />
        {others.length > 0 && (
          <div className="max-h-28 overflow-y-auto">
            {others.slice(0, 20).map(([s, n]) => (
              <button key={s} onClick={() => setSymbol(s)} className="block w-full truncate rounded px-1 py-0.5 text-left text-2xs hover:bg-ink-850">
                <b className="text-ink-100">{s}</b> <span className="text-ink-500">{new Date(n.updatedAt).toLocaleDateString()}</span> <span className="text-ink-400">{n.text}</span>
              </button>
            ))}
          </div>
        )}
        <div className="text-[10px] text-ink-600">Headline news needs a news data feed, which isn't connected.</div>
      </div>
    </div>
  );
}
