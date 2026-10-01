import type { FounderWorkspaceData } from '@/lib/founder/types';

/**
 * Display-only formatting for founder values. Every number arrives from the API with its unit; these helpers choose
 * a locale representation (micro-dollars read as dollars, minor units as the currency) and never aggregate anything.
 */

const MICRO = 1_000_000;
/** Amounts below this many major units keep their cents (a $2.50 AI cost is not "$3"); larger ones read as whole units. */
const CENTS_BELOW = 10_000;

function currencyFormat(currency: string | null | undefined, fractionDigits: number) {
  try {
    return new Intl.NumberFormat('en', { style: 'currency', currency: currency || 'USD', maximumFractionDigits: fractionDigits, minimumFractionDigits: fractionDigits });
  } catch {
    return new Intl.NumberFormat('en', { style: 'currency', currency: 'USD', maximumFractionDigits: fractionDigits, minimumFractionDigits: fractionDigits });
  }
}

/** Every unit the activated metrics and the Demo adapter emit; the server names the unit, this only chooses a representation. */
export function formatMetricValue(value: number | null | undefined, unit: string, currency?: string | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'Unavailable';
  switch (unit) {
    case 'usd_micro':
    case 'currency_micro':
    case 'micro':
      return currencyFormat(currency, Math.abs(value / MICRO) < CENTS_BELOW ? 2 : 0).format(value / MICRO);
    case 'currency_minor':
    case 'currency_minor_per_outcome':
    case 'currency_minor_per_workspace':
    case 'minor':
    case 'cents':
      return currencyFormat(currency, Math.abs(value / 100) < CENTS_BELOW ? 2 : 0).format(value / 100);
    case 'millicredits':
      return `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value / 1000)} credits`;
    case 'usd':
    case 'currency':
      return currencyFormat(currency, 0).format(value);
    case 'percent':
      return `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value)}%`;
    case 'ratio':
      return `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value * 100)}%`;
    case 'seconds':
    case 'seconds_estimate':
      return formatDuration(value);
    case 'ms':
      return `${new Intl.NumberFormat('en', { maximumFractionDigits: 0 }).format(value)} ms`;
    case 'count':
    case '':
      return new Intl.NumberFormat('en').format(value);
    default:
      return `${new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(value)} ${unit}`;
  }
}

/** A signed change in the same unit; `null` means the comparison period has nothing measured. */
export function formatDelta(delta: number | null | undefined, unit: string, currency?: string | null): { text: string; direction: 'up' | 'down' | 'flat' } | null {
  if (delta === null || delta === undefined || !Number.isFinite(delta)) return null;
  const direction = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
  const magnitude = formatMetricValue(Math.abs(delta), unit, currency);
  return { text: direction === 'flat' ? 'No change' : `${direction === 'up' ? '+' : '−'}${magnitude}`, direction };
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86_400) return `${(seconds / 3600).toFixed(1).replace(/\.0$/, '')} h`;
  return `${(seconds / 86_400).toFixed(1).replace(/\.0$/, '')} d`;
}

/** ISO 8601 or epoch seconds (the founder record modules write `extract(epoch …)` floats) → epoch milliseconds. */
export function parseTime(iso: string | number | null | undefined): number | null {
  if (typeof iso === 'number') {
    if (!Number.isFinite(iso) || iso <= 0) return null;
    return iso < 1e12 ? iso * 1000 : iso;
  }
  if (!iso) return null;
  const time = new Date(iso).getTime();
  return Number.isFinite(time) ? time : null;
}

/** "just now", "5 min ago", "3 h ago", "2 d ago", else the short date. */
export function formatRelative(iso: string | number | null | undefined, now: number = Date.now()): string {
  const time = parseTime(iso);
  if (time === null) return 'Not recorded';
  const seconds = Math.max(0, Math.round((now - time) / 1000));
  if (seconds < 45) return 'just now';
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`;
  if (seconds < 7 * 86_400) return `${Math.round(seconds / 86_400)} d ago`;
  return formatDateShort(iso);
}

export function formatDateShort(iso: string | number | null | undefined): string {
  const time = parseTime(iso);
  if (time === null) return 'Not recorded';
  return new Date(time).toLocaleDateString('en', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function formatDateTime(iso: string | number | null | undefined): string {
  const time = parseTime(iso);
  if (time === null) return 'Not recorded';
  return new Date(time).toLocaleString('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/**
 * The comparison a delta is measured against: the server sends the previous interval's ISO start, which reads as
 * "vs 31 Aug 2026 window"; a plain label ("30d", "previous period") is shown as given.
 */
export function formatComparisonPeriod(value: string | null | undefined): string | null {
  if (!value) return null;
  const time = /^\d{4}-\d{2}-\d{2}/.test(value) ? parseTime(value) : null;
  return time === null ? `vs ${value}` : `vs ${formatDateShort(time)} window`;
}

/** Axis tick for a series bucket: day and month, so a 90-day axis stays readable. */
export function formatTick(iso: string): string {
  const time = parseTime(iso);
  if (time === null) return iso;
  return new Date(time).toLocaleDateString('en', { month: 'short', day: 'numeric' });
}

export function scenarioKey(data?: FounderWorkspaceData | null): string {
  if (!data) return 'normal';
  if (typeof data.scenario === 'string') return data.scenario;
  return String(data.scenario?.id || data.scenario?.key || 'normal');
}

/** `snake_case` and `camelCase` labels read as words. */
export function humanize(value: unknown): string {
  return String(value ?? 'Not recorded').replaceAll('_', ' ').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase().replace(/^./, (c) => c.toUpperCase());
}
