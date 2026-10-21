// Local bridge between the browser app and the IBKR Client Portal Gateway.
// Exposes read-only JSON endpoints under /api/ibkr. No order routing.
import express from 'express';
import { createIbkrClient } from './ibkr.js';

const PORT = Number(process.env.PORT ?? 8787);
const client = createIbkrClient({
  baseUrl: process.env.IBKR_GATEWAY_URL ?? 'https://localhost:5000',
  allowSelfSigned: process.env.IBKR_ALLOW_SELF_SIGNED ? process.env.IBKR_ALLOW_SELF_SIGNED === 'true' : undefined,
});

const app = express();
const SYMBOL = /^[A-Z.\-]{1,10}$/;

const handle = (fn) => async (req, res) => {
  try {
    res.json(await fn(req));
  } catch (e) {
    res.status(e.status && e.status < 600 ? e.status : 502).json({ error: e.message });
  }
};

app.get('/api/ibkr/status', handle(() => client.status()));

app.get('/api/ibkr/history', handle((req) => {
  const symbol = String(req.query.symbol ?? '').toUpperCase();
  if (!SYMBOL.test(symbol)) throw Object.assign(new Error('bad symbol'), { status: 400 });
  const period = /^\d{1,3}[dwmy]$/.test(String(req.query.period)) ? String(req.query.period) : '1y';
  const bar = /^\d{1,3}(min|h|d|w|m)$/.test(String(req.query.bar)) ? String(req.query.bar) : '1d';
  return client.history(symbol, period, bar);
}));

app.get('/api/ibkr/snapshot', handle((req) => {
  const symbols = String(req.query.symbols ?? '').toUpperCase().split(',').filter((s) => SYMBOL.test(s)).slice(0, 50);
  return client.snapshot(symbols);
}));

app.get('/api/ibkr/summary', handle(() => client.summary()));
app.get('/api/ibkr/positions', handle(() => client.positions()));

// keep the gateway session alive while the bridge is running
setInterval(() => client.tickle(), 60_000).unref();

app.listen(PORT, '127.0.0.1', () => {
  console.log(`IBKR bridge on http://127.0.0.1:${PORT} → ${process.env.IBKR_GATEWAY_URL ?? 'https://localhost:5000'}`);
});
