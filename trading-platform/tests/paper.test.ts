import { describe, expect, it } from 'vitest';
import { buildBracket, newAccount, processPrice } from '../src/lib/paper';

describe('paper trading engine', () => {
  it('fills a limit entry, then the target cancels the OCA stop', () => {
    let acct = newAccount();
    acct.orders = buildBracket({ symbol: 'AAPL', side: 'BUY', qty: 10, entryType: 'LMT', entryPrice: 100, target: 110, stop: 95 });
    // above the limit: nothing happens, children stay dormant even though 95 < price
    let r = processPrice(acct, 'AAPL', 101);
    expect(r.fills).toHaveLength(0);
    r = processPrice(r.account, 'AAPL', 99.5);
    expect(r.fills.map((f) => f.label)).toEqual(['Entry']);
    expect(r.fills[0].fillPrice).toBe(99.5);
    expect(r.account.positions.AAPL.qty).toBe(10);
    r = processPrice(r.account, 'AAPL', 111);
    expect(r.fills.map((f) => f.label)).toEqual(['Target']);
    expect(r.fills[0].fillPrice).toBe(111);
    acct = r.account;
    expect(acct.orders.find((o) => o.label === 'Stop')!.status).toBe('CANCELLED');
    expect(acct.positions.AAPL).toBeUndefined();
    expect(acct.realized).toBeCloseTo(115);
  });

  it('trails a stop behind the high and exits on the pullback', () => {
    const acct = newAccount();
    acct.orders = buildBracket({ symbol: 'TSLA', side: 'BUY', qty: 1, entryType: 'MKT', trail: 2, stop: 90 });
    let r = processPrice(acct, 'TSLA', 100);
    expect(r.fills.map((f) => f.label)).toEqual(['Entry']);
    for (const p of [102, 105, 104]) r = processPrice(r.account, 'TSLA', p);
    expect(r.fills).toHaveLength(0);
    r = processPrice(r.account, 'TSLA', 102.9);
    expect(r.fills.map((f) => f.label)).toEqual(['Trail']);
    expect(r.account.orders.find((o) => o.label === 'Stop')!.status).toBe('CANCELLED');
    expect(r.account.realized).toBeCloseTo(2.9);
  });

  it('handles short entries with a buy stop', () => {
    const acct = newAccount();
    acct.orders = buildBracket({ symbol: 'X', side: 'SELL', qty: 5, entryType: 'MKT', stop: 105, target: 90 });
    let r = processPrice(acct, 'X', 100);
    expect(r.account.positions.X.qty).toBe(-5);
    r = processPrice(r.account, 'X', 106);
    expect(r.fills[0].label).toBe('Stop');
    expect(r.account.realized).toBeCloseTo(-30);
    expect(r.account.cash).toBeCloseTo(100_000 - 30);
  });
});

describe('day P&L', () => {
  it('measures from entry for positions opened today and from prior close otherwise', async () => {
    const { dayPnl } = await import('../src/lib/paper');
    const now = Date.UTC(2026, 9, 21, 18);
    expect(dayPnl({ symbol: 'X', qty: 10, avgPrice: 100, openedAt: now - 3600_000 }, 102, 105, now)).toBeCloseTo(20);
    expect(dayPnl({ symbol: 'X', qty: 10, avgPrice: 100, openedAt: now - 3 * 86400_000 }, 102, 105, now)).toBeCloseTo(-30);
  });
});
