import { useEffect, useState } from 'react';
import { Landing } from './components/Landing';
import { TopBar } from './components/TopBar';
import { Workspace } from './components/Workspace';
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
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar onHome={() => (window.location.hash = '')} />
      <Workspace />
      <Toasts />
    </div>
  );
}
