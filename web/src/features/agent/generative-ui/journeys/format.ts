/**
 * Formatting for journey views (lane E). Pure functions, no React.
 *
 *   - Unknown is not zero: every number formatter returns null for null/undefined/NaN, and callers print the locale's
 *     "Unknown" / "Unavailable" / "Not measured" word instead. Nothing here coerces a missing value to 0.
 *   - Instants are formatted in the zone the record carries (or the zone the query was resolved in) and the zone is
 *     always printed next to the time, so a calendar entry never silently shifts into the browser's zone.
 *   - Formatting never throws: an invalid zone or date falls back to the server's own local string.
 */
import { INTL_TAG, type JourneyLocale } from './copy';

export function isKnownNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function formatCount(value: unknown, locale: JourneyLocale): string | null {
  if (!isKnownNumber(value)) return null;
  return new Intl.NumberFormat(INTL_TAG[locale], { maximumFractionDigits: 0 }).format(value);
}

export function formatNumber(value: unknown, locale: JourneyLocale, digits = 2): string | null {
  if (!isKnownNumber(value)) return null;
  return new Intl.NumberFormat(INTL_TAG[locale], { maximumFractionDigits: digits }).format(value);
}

export function formatPercent(value: unknown, locale: JourneyLocale): string | null {
  if (!isKnownNumber(value)) return null;
  return new Intl.NumberFormat(INTL_TAG[locale], { style: 'percent', maximumFractionDigits: 1 }).format(value);
}

/** Money stored in micro units (1/1,000,000) of `currency`. */
export function formatMicroMoney(micro: unknown, currency: string | null | undefined, locale: JourneyLocale): string | null {
  if (!isKnownNumber(micro)) return null;
  const amount = micro / 1_000_000;
  if (currency && /^[A-Z]{3}$/.test(currency)) {
    try {
      return new Intl.NumberFormat(INTL_TAG[locale], { style: 'currency', currency, maximumFractionDigits: amount < 1 ? 4 : 2 }).format(amount);
    } catch {
      // fall through to a plain number with the code
    }
  }
  const plain = new Intl.NumberFormat(INTL_TAG[locale], { maximumFractionDigits: amount < 1 ? 4 : 2 }).format(amount);
  return currency ? `${plain} ${currency}` : plain;
}

export function formatBytes(bytes: unknown, locale: JourneyLocale): string | null {
  if (!isKnownNumber(bytes) || bytes < 0) return null;
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat(INTL_TAG[locale], { maximumFractionDigits: unit === 0 ? 0 : 1 }).format(value)} ${units[unit]}`;
}

function validZone(zone: string | null | undefined): string | undefined {
  if (!zone) return undefined;
  try {
    new Intl.DateTimeFormat('en', { timeZone: zone });
    return zone;
  } catch {
    return undefined;
  }
}

function instant(value: string | null | undefined): Date | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? new Date(ms) : null;
}

/**
 * "Fri 9 Oct, 09:00 · Asia/Hong_Kong". `local` is the server's wall-clock string for the same instant (fallback when the
 * instant or zone can't be formatted). Returns null when neither is known.
 */
export function formatInstant(
  atUtc: string | null | undefined,
  zone: string | null | undefined,
  locale: JourneyLocale,
  local?: string | null,
  options: { withZone?: boolean; dateOnly?: boolean } = {},
): string | null {
  const date = instant(atUtc);
  const tz = validZone(zone);
  const withZone = options.withZone ?? true;
  let text: string | null = null;
  if (date) {
    const format: Intl.DateTimeFormatOptions = options.dateOnly
      ? { weekday: 'short', day: 'numeric', month: 'short', timeZone: tz ?? 'UTC' }
      : { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: tz ?? 'UTC' };
    text = new Intl.DateTimeFormat(INTL_TAG[locale], format).format(date);
    if (withZone) text = `${text} · ${tz ?? 'UTC'}`;
    return text;
  }
  if (local) {
    text = local.replace('T', ' ');
    if (withZone && zone) text = `${text} · ${zone}`;
    return text;
  }
  return null;
}

/** A calendar date (YYYY-MM-DD) shown as a locale date without shifting it through any zone. */
export function formatCalendarDate(day: string | null | undefined, locale: JourneyLocale): string | null {
  if (!day || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const [y, m, d] = day.split('-').map(Number);
  const date = new Date(Date.UTC(y, m - 1, d, 12));
  return new Intl.DateTimeFormat(INTL_TAG[locale], { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' }).format(date);
}

/** Server ISO time (as-of, fetched-at) in the person's own zone, with the zone named. */
export function formatAsOf(value: string | null | undefined, zone: string | null | undefined, locale: JourneyLocale): string | null {
  return formatInstant(value, zone ?? 'UTC', locale, null, { withZone: true });
}

/** Text length the way people count it (code points), for platform limits. */
export function textLength(text: string): number {
  return Array.from(text).length;
}
