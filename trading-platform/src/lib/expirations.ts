const DAY = 86400000;

export interface Expiry { date: Date; dte: number; weekly: boolean; label: string }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Upcoming option expirations: every Friday within `maxDays`; third Fridays are monthlies. */
export function upcomingExpirations(maxDays: number, now = new Date()): Expiry[] {
  const out: Expiry[] = [];
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const d = new Date(start);
  d.setUTCDate(d.getUTCDate() + ((5 - d.getUTCDay() + 7) % 7)); // next Friday (today if Friday)
  for (; (d.getTime() - start.getTime()) / DAY <= maxDays; d.setUTCDate(d.getUTCDate() + 7)) {
    const dte = Math.round((d.getTime() - start.getTime()) / DAY);
    const weekly = !(d.getUTCDate() >= 15 && d.getUTCDate() <= 21);
    // beyond ~6 weeks only list monthlies, like most chains
    if (weekly && dte > 45) continue;
    const date = new Date(d);
    out.push({ date, dte, weekly, label: `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()} ${date.getUTCFullYear()}${weekly ? ' (W)' : ''}` });
  }
  return out;
}

export const shortExpiry = (e: Expiry) => `${MONTHS[e.date.getUTCMonth()]}${e.date.getUTCDate()}`;
