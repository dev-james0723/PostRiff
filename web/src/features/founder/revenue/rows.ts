import { isMeasured, overallState, type CategoryItem, type Series, type SeriesDescriptor, type SeriesPoint } from '../customers/kit/metric';
import type { PeriodKey } from '../customers/kit/period';
import type { FounderMode, MetricRow } from '../customers/kit/types';
import { BRIDGE_STEPS, type BridgeBar, type BridgeStep, type InvoiceRow, type Movement, type RouteInterval } from './types';

/**
 * Pure adapters for the Revenue page. Metric rows arrive with the query interval on every row and the day bucket in
 * `dimensions.window`, so these pivot by that label. They relabel, filter and lay out server values; the only numbers
 * produced here are bar positions for the waterfall (geometry), never a total, rate or delta that is displayed.
 */

export const STEP_LABEL: Record<BridgeStep, string> = {
  opening: 'Opening MRR',
  new: 'New',
  expansion: 'Expansion',
  reactivation: 'Reactivation',
  contraction: 'Contraction',
  churn: 'Churn',
  closing: 'Closing MRR'
};

/** Axis labels short enough for seven bars on a 390-pixel screen. */
export const STEP_SHORT: Record<BridgeStep, string> = {
  opening: 'Open',
  new: 'New',
  expansion: 'Expand',
  reactivation: 'React.',
  contraction: 'Contract',
  churn: 'Churn',
  closing: 'Close'
};

export function isMovement(step: string | null | undefined): step is Movement {
  return step === 'new' || step === 'expansion' || step === 'reactivation' || step === 'contraction' || step === 'churn';
}

function dims(row: MetricRow): Record<string, string> {
  return row.dimensions ?? {};
}

/** Rows that carry every named dimension; rows with a day bucket are excluded unless `window` is named. */
export function rowsWith(rows: readonly MetricRow[], names: readonly string[]): MetricRow[] {
  return rows.filter((row) => {
    const values = dims(row);
    if (!names.includes('window') && 'window' in values) return false;
    return names.every((name) => name in values);
  });
}

/** The native currencies present in a result, in the server's order; amounts are never combined across them. */
export function currenciesOf(rows: readonly MetricRow[]): string[] {
  const seen: string[] = [];
  for (const row of rows) {
    const currency = row.currency ?? dims(row).currency ?? null;
    if (currency && !seen.includes(currency)) seen.push(currency);
  }
  return seen;
}

function inCurrency(row: MetricRow, currency: string | null): boolean {
  if (!currency) return true;
  return (row.currency ?? dims(row).currency ?? null) === currency;
}

/** Whole-interval rows grouped by one dimension, for the kit's CategoryBars. Unmeasured rows keep `null`. */
export function categoryItems(rows: readonly MetricRow[], dimension: string, currency: string | null = null): CategoryItem[] {
  return rowsWith(rows, [dimension])
    .filter((row) => inCurrency(row, currency))
    .map((row, index) => ({ key: `c${index}`, label: dims(row)[dimension] ?? 'unknown', value: isMeasured(row) ? row.value : null, dataState: row.dataState, row }));
}

/**
 * Day-bucketed rows (`dimensions.window`, `YYYY-MM-DD`) as the kit's chart series: one point per day, one key per series
 * (a dimension value, or the metric id). A day without a measured row stays `null`, a gap rather than a zero.
 */
export function windowSeries(rows: readonly MetricRow[], dimension: string | null = null, currency: string | null = null): Series {
  const buckets = rows.filter((row) => typeof dims(row).window === 'string' && inCurrency(row, currency));
  const keys = new Map<string, SeriesDescriptor>();
  const byDay = new Map<string, SeriesPoint>();
  for (const row of buckets) {
    const label = dimension ? (dims(row)[dimension] ?? 'unknown') : row.metricId;
    let descriptor = keys.get(label);
    if (!descriptor) {
      descriptor = { key: `s${keys.size}`, label, measured: 0 };
      keys.set(label, descriptor);
    }
    const day = dims(row).window;
    let point = byDay.get(day);
    if (!point) {
      point = { t: day };
      byDay.set(day, point);
    }
    if (isMeasured(row)) {
      point[descriptor.key] = row.value;
      descriptor.measured += 1;
    } else if (!(descriptor.key in point)) {
      point[descriptor.key] = null;
    }
  }
  const points = Array.from(byDay.values()).toSorted((a, b) => a.t.localeCompare(b.t));
  const first = buckets[0];
  return { points, series: Array.from(keys.values()), unit: first?.unit ?? 'count', currency: first?.currency ?? currency, dataState: overallState(buckets) };
}

/**
 * The waterfall for one currency from `mrr_movements` grouped by movement. Each step keeps the server's value and
 * state; `base`/`size` place the floating bar. `complete` is false unless all seven steps are measured, in which case
 * the page shows the reconciliation table instead of drawing a bridge from partial pieces.
 */
export function bridgeBars(rows: readonly MetricRow[], currency: string | null): { bars: BridgeBar[]; complete: boolean; reconciles: boolean } {
  const mine = rowsWith(rows, ['movement']).filter((row) => inCurrency(row, currency));
  let running = 0;
  let complete = true;
  const bars: BridgeBar[] = BRIDGE_STEPS.map((step) => {
    const row = mine.find((candidate) => dims(candidate).movement === step) ?? null;
    const measured = row !== null && (row.dataState === 'measured' || row.dataState === 'partial' || row.dataState === 'stale' || row.dataState === 'synthetic') && typeof row.value === 'number';
    if (!measured) complete = false;
    const value = measured ? (row!.value as number) : null;
    const customers = row && typeof row.coverage?.known === 'number' ? row.coverage.known : null;
    const common = { step, label: STEP_LABEL[step], short: STEP_SHORT[step], value, dataState: row?.dataState ?? 'unavailable', customers };
    if (value === null) return { ...common, base: 0, size: 0, direction: step === 'opening' || step === 'closing' ? 'total' : 'up' };
    if (step === 'opening') {
      running = value;
      return { ...common, base: 0, size: value, direction: 'total' };
    }
    if (step === 'closing') return { ...common, base: 0, size: value, direction: 'total' };
    const base = value >= 0 ? running : running + value;
    running += value;
    return { ...common, base, size: Math.abs(value), direction: value >= 0 ? 'up' : 'down' };
  });
  const closing = bars[bars.length - 1].value;
  return { bars, complete, reconciles: complete && closing === running };
}

/** Actual daily MRR (solid) beside the scenario line (dashed), keyed by day; each side is `null` where it has no row. */
export function forecastPoints(actualRows: readonly MetricRow[], scenarioRows: readonly MetricRow[], currency: string | null): Array<{ t: string; actual: number | null; scenario: number | null }> {
  const byDay = new Map<string, { t: string; actual: number | null; scenario: number | null }>();
  const take = (rows: readonly MetricRow[], key: 'actual' | 'scenario') => {
    for (const row of rows) {
      const day = dims(row).window;
      if (typeof day !== 'string' || !inCurrency(row, currency)) continue;
      const point = byDay.get(day) ?? { t: day, actual: null, scenario: null };
      point[key] = isMeasured(row) || (row.dataState === 'partial' && typeof row.value === 'number') ? row.value : null;
      byDay.set(day, point);
    }
  };
  take(actualRows, 'actual');
  take(scenarioRows, 'scenario');
  return Array.from(byDay.values()).toSorted((a, b) => a.t.localeCompare(b.t));
}

/** "Needs 30 days of billing events; 12 so far." for rows the server marked insufficient_history. */
export function historyNote(row: Pick<MetricRow, 'history' | 'reason'> | null | undefined, what = 'billing events'): string | null {
  const history = row?.history;
  if (row?.reason !== 'insufficient_history' || !history) return null;
  return `Needs ${history.requiredDays} days of ${what}; ${history.availableDays} so far.`;
}

/** Plain words for the reasons the revenue metrics and routes return. */
export function reasonText(reason: string | null | undefined): string | null {
  switch (reason) {
    case null:
    case undefined:
      return null;
    case 'not_instrumented':
      return 'No billing event has been recorded yet; Stripe is not live, so nothing has been collected.';
    case 'insufficient_history':
      return 'Not enough history yet for this definition.';
    case 'source_not_configured':
      return 'The billing projections are not installed in this environment yet.';
    case 'demo_not_simulated':
      return 'The Demo dataset has no subscription-change history, so this is not simulated.';
    default:
      return reason.replaceAll('_', ' ');
  }
}

/**
 * Query strings for the revenue routes. Live sends the exact interval the page's metric queries use so a drill-down
 * lists the customers behind the same bar; Demo sends the period, which the server anchors at the Demo dataset's date.
 */
export function routeSearch(mode: FounderMode, period: PeriodKey | `${number}d`, interval: RouteInterval | null, extra: Record<string, string | null | undefined> = {}): string {
  const params = new URLSearchParams({ mode });
  if (mode === 'live' && interval) {
    params.set('start', interval.start);
    params.set('end', interval.end);
  } else {
    params.set('period', period === 'mtd' || period === '6m' || period === '12w' ? '90d' : period);
  }
  for (const [key, value] of Object.entries(extra)) if (value) params.set(key, value);
  return `?${params.toString()}`;
}

/** Invoices a customer still owes: open (payment failed or pending) and uncollectible. */
export function dunningRows(rows: readonly InvoiceRow[]): InvoiceRow[] {
  return rows.filter((row) => row.status === 'open' || row.status === 'uncollectible');
}

/** The Ask Rafii request behind "Draft reminder": ids only; Founder Rafii drafts with founder_draft_message and sends nothing. */
export function draftReminderPrompt(row: Pick<InvoiceRow, 'invoiceId' | 'status'>): string {
  return `Draft a payment reminder (founder_draft_message, kind payment_reminder) for the customer behind invoice ${row.invoiceId}, which is ${row.status}. Show me the draft only; do not send anything.`;
}

/** A short, non-identifying label for an id in a table cell. */
export function shortId(value: string | null | undefined): string {
  if (!value) return 'Not recorded';
  return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}
