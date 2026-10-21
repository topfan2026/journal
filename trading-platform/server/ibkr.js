// Thin read-only client for the Interactive Brokers Client Portal Web API.
// The gateway runs on your machine (default https://localhost:5000) and holds your
// logged-in session; this module never sees your IBKR password.
import https from 'node:https';
import http from 'node:http';

export function createIbkrClient({ baseUrl = 'https://localhost:5000', allowSelfSigned } = {}) {
  const url = new URL(baseUrl);
  const local = ['localhost', '127.0.0.1', '::1'].includes(url.hostname);
  // The gateway ships with a self-signed certificate; only accept that for a local gateway.
  const agent = url.protocol === 'https:' ? new https.Agent({ rejectUnauthorized: !(allowSelfSigned ?? local), keepAlive: true }) : undefined;
  const conids = new Map();
  let accountsPrimed = false;

  function request(method, path, body) {
    const target = new URL(`/v1/api${path}`, url);
    const lib = target.protocol === 'https:' ? https : http;
    const payload = body ? JSON.stringify(body) : undefined;
    return new Promise((resolve, reject) => {
      const req = lib.request(target, {
        method, agent, timeout: 10000,
        headers: { 'User-Agent': 'chartdesk/0.1', Accept: 'application/json', ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) } : {}) },
      }, (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          if (res.statusCode >= 400) return reject(Object.assign(new Error(`IBKR ${res.statusCode}: ${data.slice(0, 200)}`), { status: res.statusCode }));
          try { resolve(data ? JSON.parse(data) : null); } catch { reject(new Error(`IBKR returned non-JSON: ${data.slice(0, 120)}`)); }
        });
      });
      req.on('timeout', () => req.destroy(new Error('IBKR gateway timed out')));
      req.on('error', reject);
      if (payload) req.write(payload);
      req.end();
    });
  }
  const get = (p) => request('GET', p);

  async function primeAccounts() {
    // /iserver/accounts must be called once per session before market data requests.
    if (accountsPrimed) return;
    await get('/iserver/accounts');
    accountsPrimed = true;
  }

  async function conid(symbol) {
    const key = symbol.toUpperCase();
    if (conids.has(key)) return conids.get(key);
    const res = await get(`/iserver/secdef/search?symbol=${encodeURIComponent(key)}&secType=STK`);
    const list = Array.isArray(res) ? res : [];
    const hit = list.find((r) => r.symbol?.toUpperCase() === key && /NASDAQ|NYSE|ARCA|AMEX|BATS/i.test(r.description ?? '')) ?? list.find((r) => r.symbol?.toUpperCase() === key) ?? list[0];
    if (!hit?.conid) throw Object.assign(new Error(`No IBKR contract for ${key}`), { status: 404 });
    const id = Number(hit.conid);
    conids.set(key, id);
    return id;
  }

  return {
    async status() {
      try {
        const s = await request('POST', '/iserver/auth/status');
        return { reachable: true, authenticated: !!s?.authenticated, connected: !!s?.connected, message: s?.fail || undefined };
      } catch (e) {
        return { reachable: e.status !== undefined, authenticated: false, connected: false, message: e.message };
      }
    },

    tickle: () => request('POST', '/tickle').catch(() => null),

    async history(symbol, period = '1y', bar = '1d') {
      await primeAccounts();
      const id = await conid(symbol);
      const res = await get(`/iserver/marketdata/history?conid=${id}&period=${encodeURIComponent(period)}&bar=${encodeURIComponent(bar)}&outsideRth=false`);
      const factor = Number(res?.volumeFactor ?? 1) || 1;
      return (res?.data ?? []).map((d) => {
        // daily bars: normalise to midnight UTC so they line up with the chart's day grid
        const day = new Date(d.t);
        const time = bar.endsWith('d') ? Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate()) / 1000 : Math.floor(d.t / 1000);
        return { time, open: d.o, high: d.h, low: d.l, close: d.c, volume: Math.round(d.v * factor) };
      });
    },

    async snapshot(symbols) {
      await primeAccounts();
      const pairs = await Promise.all(symbols.map(async (s) => { try { return [s, await conid(s)]; } catch { return null; } }));
      const ok = pairs.filter(Boolean);
      if (!ok.length) return [];
      // 31=last 84=bid 86=ask 83=change% 87=volume. The first call for a conid may return no fields yet.
      const res = await get(`/iserver/marketdata/snapshot?conids=${ok.map(([, c]) => c).join(',')}&fields=31,84,86,83,87`);
      const byConid = new Map((Array.isArray(res) ? res : []).map((r) => [Number(r.conid), r]));
      return ok.map(([symbol, c]) => {
        const r = byConid.get(c) ?? {};
        return { symbol, last: num(r['31']), bid: num(r['84']), ask: num(r['86']), changePct: num(r['83']), volume: vol(r['87']) };
      });
    },

    async accountId() {
      const accts = await get('/portfolio/accounts');
      const id = accts?.[0]?.accountId ?? accts?.[0]?.id;
      if (!id) throw Object.assign(new Error('No IBKR accounts visible to this session'), { status: 404 });
      return id;
    },

    async summary() {
      const id = await this.accountId();
      const s = await get(`/portfolio/${id}/summary`);
      const amt = (k) => (s?.[k]?.amount ?? null);
      return { accountId: id, netLiquidation: amt('netliquidation'), buyingPower: amt('buyingpower'), cash: amt('totalcashvalue') };
    },

    async positions() {
      const id = await this.accountId();
      const out = [];
      for (let page = 0; page < 10; page++) {
        const rows = await get(`/portfolio/${id}/positions/${page}`);
        if (!Array.isArray(rows) || !rows.length) break;
        out.push(...rows);
        if (rows.length < 100) break;
      }
      return out.map((p) => ({
        symbol: p.ticker ?? p.contractDesc, qty: p.position, avgPrice: p.avgPrice ?? p.avgCost ?? 0,
        mktPrice: p.mktPrice ?? 0, unrealizedPnl: p.unrealizedPnl ?? 0, assetClass: p.assetClass ?? '',
      }));
    },
  };
}

// Snapshot fields come back as strings, sometimes prefixed (C = prior close, H = halted).
export function num(v) {
  if (v === undefined || v === null || v === '') return null;
  const n = parseFloat(String(v).replace(/^[A-Z]+/, '').replace(/,/g, ''));
  return Number.isFinite(n) ? n : null;
}

export function vol(v) {
  if (v === undefined || v === null || v === '') return null;
  const m = String(v).replace(/,/g, '').match(/^([\d.]+)\s*([KMB])?$/i);
  if (!m) return null;
  const mult = { K: 1e3, M: 1e6, B: 1e9 }[m[2]?.toUpperCase()] ?? 1;
  return Math.round(parseFloat(m[1]) * mult);
}
