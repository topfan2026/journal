import { useEffect, useState } from 'react';
import { Landing } from './components/Landing';
import { AppToolbar } from './components/AppToolbar';
import { Page, PageTabs } from './components/Pages';
import { SymbolEntry } from './components/SymbolEntry';
import { Toasts } from './components/Toasts';
import { useMarketFeed } from './lib/useMarketFeed';

const route = () => (window.location.hash.startsWith('#/app') ? 'app' : 'home');

export default function App() {
  const [page, setPage] = useState(route);
  useEffect(() => {
    const on = () => setPage(route());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  useMarketFeed();

  if (page === 'home') return <><Landing onLaunch={() => (window.location.hash = '#/app')} /><Toasts /></>;
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-ink-950">
      <AppToolbar />
      <div className="min-h-0 flex-1"><Page /></div>
      <PageTabs />
      <SymbolEntry />
      <Toasts />
    </div>
  );
}
