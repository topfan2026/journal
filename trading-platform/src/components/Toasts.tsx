import { AnimatePresence, motion } from 'framer-motion';
import { useWorkspace } from '../store/workspace';

export function Toasts() {
  const toasts = useWorkspace((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 40 }}
            className={`rounded border-l-4 bg-ink-800 px-3 py-2 text-xs shadow-xl ${t.tone === 'up' ? 'border-up' : t.tone === 'down' ? 'border-down' : 'border-accent'}`}
          >
            {t.text}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
