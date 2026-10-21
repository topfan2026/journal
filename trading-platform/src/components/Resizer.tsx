/** A drag handle between panels. Reports the pointer delta along its axis. */
export function Resizer({ axis, onDelta }: { axis: 'x' | 'y'; onDelta: (d: number) => void }) {
  const onDown = (e: React.PointerEvent) => {
    e.preventDefault();
    let last = axis === 'x' ? e.clientX : e.clientY;
    const move = (ev: PointerEvent) => {
      const cur = axis === 'x' ? ev.clientX : ev.clientY;
      onDelta(cur - last);
      last = cur;
    };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); document.body.style.cursor = ''; };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
  };
  return (
    <div
      onPointerDown={onDown}
      className={`group relative z-20 shrink-0 bg-ink-800 hover:bg-accent ${axis === 'x' ? 'w-1 cursor-col-resize' : 'h-1 cursor-row-resize'}`}
    />
  );
}
