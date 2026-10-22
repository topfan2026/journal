import { describe, expect, it } from 'vitest';
import { useWorkspace } from '../src/store/workspace';
import { useMarket } from '../src/store/market';
import { stepForwardTests, ftPosition } from '../src/lib/forwardTest';
import type { StrategyDef } from '../src/lib/backtest';

describe('forward test runner', () => {
  it('enters once per bar when rules are true and exits when an exit rule fires', () => {
    const def: StrategyDef = {
      id: 'ft-def', name: 'always', direction: 'long',
      entry: [{ id: 'e', left: 'price', op: '>', right: { kind: 'value', value: 0 } }],
      exit: [], sizing: { mode: 'shares', value: 10 }, commission: 0, slippagePct: 0, capital: 10_000, stopPct: 5,
    };
    const ws = useWorkspace.getState();
    ws.saveStrategy(def);
    ws.set('forwardTests', [{ id: 'ft1', strategyId: def.id, name: def.name, symbols: ['AAPL'], tf: 'D', startedAt: 0, active: true, lastSignal: {}, entryBar: {}, log: [] }]);

    stepForwardTests();
    stepForwardTests(); // same bar: must not enter twice
    let s = useWorkspace.getState();
    expect(ftPosition(s.paper.orders, 'ft:ft1', 'AAPL').qty).toBe(10);
    expect(s.paper.orders.filter((o) => o.tag === 'ft:ft1' && o.label === 'Stop' && o.status === 'WORKING')).toHaveLength(1);

    // switch the strategy to exit on any bar, and advance to a new bar
    useWorkspace.getState().saveStrategy({ ...def, exit: [{ id: 'x', left: 'price', op: '>', right: { kind: 'value', value: 0 } }] });
    const bars = useMarket.getState().bars.AAPL;
    const last = bars[bars.length - 1];
    useMarket.setState((m) => ({ bars: { ...m.bars, AAPL: [...bars, { ...last, time: last.time + 86400 }] } }));
    stepForwardTests();
    s = useWorkspace.getState();
    expect(ftPosition(s.paper.orders, 'ft:ft1', 'AAPL').qty).toBe(0);
    expect(s.paper.orders.filter((o) => o.tag === 'ft:ft1' && o.status === 'WORKING')).toHaveLength(0);
    expect(s.forwardTests[0].log.map((l) => l.text.split(' ')[0])).toEqual(['BUY', 'EXIT']);
  });
});
