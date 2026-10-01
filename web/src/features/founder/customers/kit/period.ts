/**
 * Query periods for the domain pages (PRD §7.2 defaults). Intervals are half-open `[start, end)` in UTC and carry
 * the viewer's zone so the server can bucket days locally; the server decides the grain and keeps ≤1000 points.
 * Only dates are derived here, never business numbers.
 */

export type PeriodKey = '7d' | '30d' | '90d' | 'mtd' | '6m' | '12w';

export const PERIOD_LABEL: Record<PeriodKey, string> = {
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
  '90d': 'Last 90 days',
  mtd: 'Month to date',
  '6m': 'Last 6 months',
  '12w': 'Last 12 weeks'
};

export const PERIOD_SHORT: Record<PeriodKey, string> = {
  '7d': '7d',
  '30d': '30d',
  '90d': '90d',
  mtd: 'MTD',
  '6m': '6 mo',
  '12w': '12 wk'
};

export function resolvedTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function utcMidnight(date: Date): Date {
  const copy = new Date(date);
  copy.setUTCHours(0, 0, 0, 0);
  return copy;
}

/** The interval a period names, ending now; `now` is injectable so tests and receipts stay reproducible. */
export function periodInterval(period: PeriodKey, now: Date = new Date(), timeZone: string = resolvedTimeZone()): { start: string; end: string; timeZone: string } {
  const start = utcMidnight(now);
  switch (period) {
    case '7d':
      start.setUTCDate(start.getUTCDate() - 7);
      break;
    case '30d':
      start.setUTCDate(start.getUTCDate() - 30);
      break;
    case '90d':
      start.setUTCDate(start.getUTCDate() - 90);
      break;
    case '12w':
      start.setUTCDate(start.getUTCDate() - 7 * 12);
      break;
    case 'mtd':
      start.setUTCDate(1);
      break;
    case '6m':
      start.setUTCDate(1);
      start.setUTCMonth(start.getUTCMonth() - 5);
      break;
  }
  return { start: start.toISOString(), end: now.toISOString(), timeZone };
}

/** Whole days a period spans, for copy such as "over 30 days"; the server's own interval is the authority. */
export function periodDays(period: PeriodKey, now: Date = new Date()): number {
  const { start, end } = periodInterval(period, now, 'UTC');
  return Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000);
}

export function isPeriodKey(value: string | null | undefined): value is PeriodKey {
  return value !== null && value !== undefined && Object.hasOwn(PERIOD_LABEL, value);
}
