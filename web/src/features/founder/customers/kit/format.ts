import type { DataState, MetricRow, RecordRow } from './types';

/**
 * Display formatting only. A value is written as the server sent it (minor units, USD micro, ratios); nothing is
 * summed, averaged or derived. An unreported value is a word ("Unavailable"), never 0 (`features/analytics` rule).
 */

export const UNAVAILABLE = 'Unavailable';

const locale = 'en';

function currencyFormat(currency: string | null | undefined, fractionDigits: number) {
  try {
    return new Intl.NumberFormat(locale, { style: 'currency', currency: currency || 'USD', minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
  } catch {
    return new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD', minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
  }
}

/** Minor currency units (cents) as money. */
export function minor(amount: number | null | undefined, currency: string | null | undefined = 'USD'): string {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return UNAVAILABLE;
  return currencyFormat(currency, 2).format(amount / 100);
}

/** USD micro (1e-6) as money with enough precision for per-request costs. */
export function usdMicro(micro: number | null | undefined): string {
  if (typeof micro !== 'number' || !Number.isFinite(micro)) return UNAVAILABLE;
  const dollars = micro / 1_000_000;
  const digits = Math.abs(dollars) >= 1 ? 2 : 4;
  return currencyFormat('USD', digits).format(dollars);
}

export function count(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNAVAILABLE;
  return new Intl.NumberFormat(locale).format(value);
}

/** A ratio the server already computed, written as a percentage. */
export function ratio(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNAVAILABLE;
  return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(value);
}

export function seconds(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNAVAILABLE;
  if (value < 60) return `${Math.round(value)} s`;
  if (value < 3600) return `${Math.round(value / 60)} min`;
  if (value < 86_400) return `${(value / 3600).toFixed(1)} h`;
  return `${(value / 86_400).toFixed(1)} d`;
}

export function millicredits(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNAVAILABLE;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value / 1000)} credits`;
}

/** The right formatter for a metric row's unit; unknown units keep the raw number with the unit name. */
export function metricValue(row: Pick<MetricRow, 'value' | 'unit' | 'currency' | 'dataState'> | null | undefined): string {
  if (!row || row.value === null || row.value === undefined || row.dataState === 'unavailable') return UNAVAILABLE;
  const value = row.value;
  switch (row.unit) {
    case 'currency_minor':
    case 'currency_minor_per_outcome':
    case 'currency_minor_per_workspace':
      return minor(value, row.currency ?? 'USD');
    case 'usd_micro':
    case 'currency_micro':
      return usdMicro(value);
    case 'ratio':
      return ratio(value);
    case 'count':
      return count(value);
    case 'seconds':
    case 'seconds_estimate':
      return seconds(value);
    case 'millicredits':
      return millicredits(value);
    default:
      return `${count(value)} ${row.unit}`.trim();
  }
}

/** A Recharts axis/tooltip formatter for one unit. */
export function unitFormatter(unit: string | undefined, currency?: string | null): (value: number) => string {
  return (value) => metricValue({ value, unit: unit ?? 'count', currency, dataState: 'measured' });
}

/**
 * A server timestamp as epoch milliseconds, or null. Accepts ISO 8601 strings (metrics, follow-ups) and epoch seconds
 * (the founder record modules write `extract(epoch from …)` floats); a number below 1e12 is read as seconds.
 */
export function timeValue(value: unknown): number | null {
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return null;
    return value < 1e12 ? value * 1000 : value;
  }
  if (typeof value !== 'string' || !value) return null;
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : null;
}

export function whenDate(value: unknown): string {
  const time = timeValue(value);
  if (time === null) return 'Not recorded';
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(time));
}

export function whenDateTime(value: unknown): string {
  const time = timeValue(value);
  if (time === null) return 'Not recorded';
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(time));
}

/** A bucket start for an axis tick: month name for monthly buckets, short date otherwise. */
export function tickDate(value: string, monthly = false): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, monthly ? { month: 'short', year: '2-digit', timeZone: 'UTC' } : { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date);
}

/** `past_due` → "past due"; nothing → "Not recorded". */
export function stateLabel(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  return String(value).replaceAll('_', ' ');
}

export function capitalize(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : value;
}

/** A record's visible name without ever synthesising one from an email. */
export function recordLabel(row: RecordRow): string {
  const candidate = row.name ?? row.title ?? row.company ?? row.label ?? row.plan;
  return typeof candidate === 'string' && candidate ? candidate : row.id;
}

/** Minutes after midnight (policy quiet hours) as `HH:MM`. */
export function minutesToClock(minutes: number | null | undefined): string {
  if (typeof minutes !== 'number' || !Number.isFinite(minutes)) return '';
  const safe = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`;
}

export function clockToMinutes(clock: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(clock.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return null;
  return hours * 60 + minutes;
}

/** Words for a data state in a status chip. */
export function dataStateLabel(state: DataState | undefined): string {
  switch (state) {
    case 'measured':
      return 'Measured';
    case 'partial':
      return 'Partial';
    case 'stale':
      return 'Stale';
    case 'synthetic':
      return 'Demo data';
    case 'suppressed':
      return 'Suppressed';
    case 'unavailable':
      return 'Not collected';
    default:
      return state ? stateLabel(state) : 'Unknown';
  }
}
