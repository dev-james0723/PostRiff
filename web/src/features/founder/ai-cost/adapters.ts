import type { CategoryItem, Series, SeriesDescriptor, SeriesPoint } from '../customers/kit/metric';
import type { DataState, MetricRow } from '../customers/kit/types';

/**
 * Pure adapters from `POST /metrics/query` rows to what the AI & API cost page draws (CONTRACTS §8.B, PRD §7.2). Rows
 * are pivoted, labelled and joined — never summed, averaged or re-derived: a percentile is shown per group exactly as the
 * server computed it, a bucket without a row is a gap (`null`) and an unreported value is `null` ("Unavailable").
 *
 * The server stamps the query interval on every row; a daily bucket is the row's `dimensions.window` (a local
 * `YYYY-MM-DD` date in the report time zone), so buckets are keyed by that label here.
 */

export function windowOf(row: Pick<MetricRow, 'dimensions'>): string | null {
  const value = row.dimensions?.window;
  return typeof value === 'string' && value ? value : null;
}

const HIDDEN: ReadonlySet<string> = new Set(['unavailable', 'not_applicable', 'suppressed']);

/** The value the server measured for this row (partial or stale included, with its state shown beside it), else null. */
export function shownValue(row: Pick<MetricRow, 'value' | 'dataState'>): number | null {
  if (HIDDEN.has(String(row.dataState))) return null;
  return typeof row.value === 'number' && Number.isFinite(row.value) ? row.value : null;
}

/** A numeric field of a row or of its measures, exactly as sent; anything else is null. */
export function numberAt(source: Record<string, unknown> | null | undefined, key: string): number | null {
  const value = source?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function measures(row: MetricRow | null | undefined): Record<string, unknown> {
  const value = row?.measures;
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

export function sampleCount(row: MetricRow | null | undefined): number | null {
  return numberAt(row as Record<string, unknown> | null | undefined, 'sampleCount');
}

/** Rows that describe the whole interval (no day bucket) and rows bucketed by local day. */
export function wholeRows(rows: readonly MetricRow[]): MetricRow[] {
  return rows.filter((row) => windowOf(row) === null);
}

export function dayRows(rows: readonly MetricRow[]): MetricRow[] {
  return rows.filter((row) => windowOf(row) !== null);
}

/** One state for a set of rows: theirs when they agree, `partial` when they differ, `unavailable` when there are none. */
export function overall(rows: readonly MetricRow[]): DataState {
  if (rows.length === 0) return 'unavailable';
  const states = new Set(rows.map((row) => row.dataState));
  return states.size === 1 ? rows[0].dataState : 'partial';
}

export interface WindowSeriesOptions {
  /** The dimension that names each series; without one the rows form a single series. */
  dimension?: string;
  /** Series order (stacking order); names the rows carry that are not listed follow in server order. */
  order?: readonly string[];
  labels?: Readonly<Record<string, string>>;
  value?: (row: MetricRow) => number | null;
  unit?: string;
}

/** Day-bucketed rows as chart points keyed by their `window` label; every point carries every series (null = gap). */
export function windowSeries(rows: readonly MetricRow[], options: WindowSeriesOptions = {}): Series {
  const buckets = dayRows(rows);
  const nameOf = (row: MetricRow) => (options.dimension ? (row.dimensions?.[options.dimension] ?? 'unknown') : 'value');
  const names: string[] = [];
  for (const row of buckets) if (!names.includes(nameOf(row))) names.push(nameOf(row));
  const ordered = options.order ? [...options.order.filter((name) => names.includes(name)), ...names.filter((name) => !options.order!.includes(name))] : names;
  const descriptors: SeriesDescriptor[] = ordered.map((name, index) => ({ key: `s${index}`, label: options.labels?.[name] ?? name.replaceAll('_', ' '), measured: 0 }));
  const byName = new Map<string, SeriesDescriptor>(ordered.map((name, index) => [name, descriptors[index]] as const));
  const byTime = new Map<string, SeriesPoint>();
  const valueOf = options.value ?? shownValue;
  for (const row of buckets) {
    const t = windowOf(row) as string;
    const point = byTime.get(t) ?? { t };
    byTime.set(t, point);
    const descriptor = byName.get(nameOf(row)) as SeriesDescriptor;
    const value = valueOf(row);
    if (value !== null) {
      point[descriptor.key] = value;
      descriptor.measured += 1;
    } else if (!(descriptor.key in point)) {
      point[descriptor.key] = null;
    }
  }
  for (const point of byTime.values()) for (const descriptor of descriptors) if (!(descriptor.key in point)) point[descriptor.key] = null;
  const points = [...byTime.values()].toSorted((a, b) => a.t.localeCompare(b.t));
  return { points, series: descriptors, unit: options.unit ?? buckets[0]?.unit ?? 'count', currency: buckets[0]?.currency ?? null, dataState: overall(buckets) };
}

/** Whole-interval rows grouped by one dimension, for bars and tables, in server order. */
export function categoryItems(rows: readonly MetricRow[], dimension: string): CategoryItem[] {
  return wholeRows(rows)
    .filter((row) => row.dimensions && dimension in row.dimensions)
    .map((row, index) => ({ key: `c${index}`, label: String(row.dimensions?.[dimension] ?? 'unknown'), value: shownValue(row), dataState: row.dataState, row }));
}

/* ---------- tokens ---------- */

/** Input (not served from cache), cached input, visible output and reasoning: the four parts of an attempt's tokens. */
export const TOKEN_TYPES = ['input', 'cached', 'output', 'reasoning'] as const;
export const TOKEN_LABELS: Readonly<Record<string, string>> = { input: 'Input', cached: 'Cached input', output: 'Output', reasoning: 'Reasoning' };

/** Tokens per day stacked by type. Axis ticks are plain counts (the card names the unit). */
export function tokenSeries(rows: readonly MetricRow[]): Series {
  return windowSeries(rows, { dimension: 'token_type', order: TOKEN_TYPES, labels: TOKEN_LABELS, unit: 'count' });
}

/* ---------- latency ---------- */

/** p50 and p95 per day as the server computed them for that day's attempts (never averaged across days or groups). */
export function latencySeries(rows: readonly MetricRow[]): Series {
  const buckets = dayRows(rows);
  const descriptors: SeriesDescriptor[] = [
    { key: 's0', label: 'p50', measured: 0 },
    { key: 's1', label: 'p95', measured: 0 }
  ];
  const points: SeriesPoint[] = [];
  for (const row of buckets.toSorted((a, b) => (windowOf(a) as string).localeCompare(windowOf(b) as string))) {
    const shown = shownValue(row) !== null;
    const p50 = shown ? numberAt(measures(row), 'p50Ms') : null;
    const p95 = shown ? (numberAt(measures(row), 'p95Ms') ?? shownValue(row)) : null;
    if (p50 !== null) descriptors[0].measured += 1;
    if (p95 !== null) descriptors[1].measured += 1;
    points.push({ t: windowOf(row) as string, s0: p50, s1: p95 });
  }
  return { points, series: descriptors, unit: 'ms', currency: null, dataState: overall(buckets) };
}

/** Fewer attempts than this make a percentile a small sample (the server's `founder_metrics_ai.SMALL_SAMPLE`). */
export const SMALL_SAMPLE = 30;

function isSmall(row: MetricRow): boolean {
  if (shownValue(row) === null) return false;
  const n = sampleCount(row);
  return row.reason === 'small_sample' || (n !== null && n < SMALL_SAMPLE);
}

/** The days whose percentiles rest on fewer than 30 attempts, as their `window` labels. */
export function smallSampleDays(rows: readonly MetricRow[]): string[] {
  return dayRows(rows)
    .filter(isSmall)
    .map((row) => windowOf(row) as string)
    .toSorted();
}

export interface LatencyRow {
  key: string;
  label: string;
  p50: number | null;
  p95: number | null;
  n: number | null;
  small: boolean;
  dataState: DataState;
  reason: string | null;
}

export function latencyTable(rows: readonly MetricRow[], dimension: string): LatencyRow[] {
  return wholeRows(rows)
    .filter((row) => row.dimensions && dimension in row.dimensions)
    .map((row, index) => {
      const shown = shownValue(row) !== null;
      const n = sampleCount(row);
      return {
        key: `l${index}`,
        label: String(row.dimensions?.[dimension] ?? 'unknown'),
        p50: shown ? numberAt(measures(row), 'p50Ms') : null,
        p95: shown ? (numberAt(measures(row), 'p95Ms') ?? shownValue(row)) : null,
        n,
        small: isSmall(row),
        dataState: row.dataState,
        reason: row.reason ?? null
      };
    });
}

/* ---------- models and routes ---------- */

export interface ModelRoute {
  model: string;
  /** All attempts on this model: the server's denominator of the retry/fallback share. */
  attempts: number | null;
  /** Attempts on the primary route (`ai_calls` by model and route). */
  primary: number | null;
  /** The model has attempts on the fallback route only, so the server returned no primary group for it. */
  noPrimary: boolean;
  /** Attempts on the fallback route and retries (attempt number above 1), as the server counted them. */
  fallback: number | null;
  retries: number | null;
  /** Share of attempts that ran on a fallback route or were a retry. */
  retryShare: number | null;
  costPerAttempt: number | null;
  dataState: DataState;
}

/** Joins three server answers by model: attempts by model and route, the retry/fallback share by model, cost per attempt by model. */
export function modelRoutes(calls: readonly MetricRow[], rates: readonly MetricRow[], costs: readonly MetricRow[]): ModelRoute[] {
  const models: string[] = [];
  const note = (row: MetricRow) => {
    const model = row.dimensions?.model;
    if (typeof model === 'string' && !models.includes(model)) models.push(model);
  };
  for (const list of [rates, calls, costs]) wholeRows(list).forEach(note);
  const pick = (list: readonly MetricRow[], model: string, route?: string) =>
    wholeRows(list).find((row) => row.dimensions?.model === model && (route === undefined || row.dimensions?.route === route)) ?? null;
  return models.map((model) => {
    const rate = pick(rates, model);
    const cost = pick(costs, model);
    const primary = pick(calls, model, 'primary');
    const fallbackRow = pick(calls, model, 'fallback');
    const rateShown = rate !== null && shownValue(rate) !== null;
    const rateMeasures = measures(rate);
    const states = [rate, cost, primary, fallbackRow].filter((row): row is MetricRow => row !== null);
    return {
      model,
      attempts: rateShown ? numberAt(rate?.coverage, 'denominator') : null,
      primary: primary ? shownValue(primary) : null,
      noPrimary: primary === null && fallbackRow !== null && shownValue(fallbackRow) !== null,
      fallback: rateShown ? numberAt(rateMeasures, 'fallbackAttempts') : fallbackRow ? shownValue(fallbackRow) : null,
      retries: rateShown ? numberAt(rateMeasures, 'retryAttempts') : null,
      retryShare: rate ? shownValue(rate) : null,
      costPerAttempt: cost ? shownValue(cost) : null,
      dataState: overall(states)
    };
  });
}

/* ---------- coverage ---------- */

/** Ledger coverage (month to date): settled actual cost beside the estimate still held for rows whose cost is unknown. */
export function ledgerCoverage(row: MetricRow | null | undefined): { known: number; unknown: number } | null {
  if (!row) return null;
  const known = shownValue(row);
  const unknown = numberAt(measures(row), 'unknownEstimateUsdMicro');
  return known !== null && unknown !== null ? { known, unknown } : null;
}

/**
 * Attempt cost provenance: provider-reported (known), price-table (estimated) and unknown attempt counts. A basis without
 * a row in a measured grouped answer had no attempts; nothing measured at all is null.
 */
export function attemptCoverage(rows: readonly MetricRow[]): { known: number; estimated: number; unknown: number } | null {
  const whole = wholeRows(rows).filter((row) => row.dimensions && 'cost_basis' in row.dimensions);
  if (whole.every((row) => shownValue(row) === null)) return null;
  const valueOf = (basis: string) => {
    const row = whole.find((item) => item.dimensions?.cost_basis === basis);
    return row ? (shownValue(row) ?? 0) : 0;
  };
  return { known: valueOf('reported'), estimated: valueOf('price_table'), unknown: valueOf('unknown') };
}

/* ---------- cost per useful outcome ---------- */

export const BASIS_LABEL: Readonly<Record<string, string>> = {
  time_back_accepted_outcomes: 'Time Back accepted outcomes',
  learning_approvals_publishes: 'Learning approvals and publishes'
};

export interface OutcomeRow {
  key: string;
  proxy: string;
  plan: string | null;
  cost: number | null;
  outcomes: number | null;
  perOutcome: number | null;
  dataState: DataState;
  reason: string | null;
}

export function outcomeTable(rows: readonly MetricRow[]): OutcomeRow[] {
  return wholeRows(rows).map((row, index) => {
    const basis = measures(row).basis;
    const plan = row.dimensions?.plan;
    return {
      key: `o${index}`,
      proxy: typeof basis === 'string' ? (BASIS_LABEL[basis] ?? basis.replaceAll('_', ' ')) : String(row.dimensions?.outcome_proxy ?? 'Not recorded').replaceAll('_', ' '),
      plan: row.dimensions && 'plan' in row.dimensions ? (typeof plan === 'string' ? plan : null) : null,
      cost: row.dataState === 'unavailable' ? null : numberAt(measures(row), 'costUsdMicro'),
      outcomes: row.dataState === 'unavailable' ? null : numberAt(measures(row), 'outcomes'),
      perOutcome: shownValue(row),
      dataState: row.dataState,
      reason: row.reason ?? null
    };
  });
}

/* ---------- month-end forecast (scenario) ---------- */

export interface ForecastPoint {
  t: string;
  actual: number | null;
  projection: number | null;
  [key: string]: number | string | null;
}

export interface ForecastBudget {
  stop: number | null;
  warn: number | null;
  status: string | null;
}

export interface ForecastView {
  points: ForecastPoint[];
  budget: ForecastBudget;
  method: string | null;
  dataState: DataState;
}

function budgetOf(row: MetricRow | null | undefined): ForecastBudget {
  const source = measures(row);
  const status = source.budgetStatus;
  return { stop: numberAt(source, 'budgetStopUsdMicro'), warn: numberAt(source, 'budgetWarnUsdMicro'), status: typeof status === 'string' ? status : null };
}

/**
 * The cumulative month as the server projected it: actual days drawn solid, projected days dashed. The last actual day
 * also starts the projection, so the dashed line continues from where the solid one ends (the same server value).
 */
export function forecastView(rows: readonly MetricRow[]): ForecastView | null {
  const days = dayRows(rows)
    .filter((row) => shownValue(row) !== null)
    .toSorted((a, b) => (windowOf(a) as string).localeCompare(windowOf(b) as string));
  if (days.length === 0) return null;
  const points: ForecastPoint[] = days.map((row) => {
    const kind = measures(row).kind;
    const value = shownValue(row);
    return { t: windowOf(row) as string, actual: kind === 'actual' ? value : null, projection: kind === 'projection' ? value : null };
  });
  const lastActual = points.map((point) => point.actual !== null).lastIndexOf(true);
  if (lastActual >= 0 && lastActual < points.length - 1) points[lastActual].projection = points[lastActual].actual;
  const method = measures(days[0]).method;
  return { points, budget: budgetOf(days[0]), method: typeof method === 'string' ? method : null, dataState: overall(days) };
}

export interface ForecastHeadline {
  total: number | null;
  mtd: number | null;
  remaining: number | null;
  slope: number | null;
  monthStart: string | null;
  monthEnd: string | null;
  method: string | null;
  basis: string | null;
  budget: ForecastBudget;
  history: { availableDays: number; requiredDays: number } | null;
  insufficient: boolean;
  dataState: DataState;
  reason: string | null;
}

export function forecastHeadline(row: MetricRow | null | undefined): ForecastHeadline | null {
  if (!row) return null;
  const source = measures(row);
  const text = (key: string) => (typeof source[key] === 'string' ? (source[key] as string) : null);
  const history = row.history && typeof row.history.availableDays === 'number' && typeof row.history.requiredDays === 'number' ? row.history : null;
  return {
    total: shownValue(row),
    mtd: numberAt(source, 'mtdActualUsdMicro'),
    remaining: numberAt(source, 'projectedRemainingUsdMicro'),
    slope: numberAt(source, 'slopeUsdMicroPerDay'),
    monthStart: text('monthStart'),
    monthEnd: text('monthEnd'),
    method: text('method'),
    basis: text('basis'),
    budget: budgetOf(row),
    history,
    insufficient: row.reason === 'insufficient_history',
    dataState: row.dataState,
    reason: row.reason ?? null
  };
}

/* ---------- reconcile ---------- */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID.test(value);
}

/** What slice F's reconcile flow needs from a queue row (`useReconcileAction().start`). */
export interface QueueTarget {
  workspaceId: string | null;
  reservationId: string | null;
  estimatedUsdMicro: number | null;
  provider: string | null;
  model: string | null;
  at: string | null;
}

/**
 * The reservation a queue row would reconcile: the row's own reservation id (an unknown settle row names the reservation
 * it settles), or the row itself when it is the reserve row. Ids that are not UUIDs (the Demo dataset's) stay null, so
 * the row cannot start a reconciliation.
 */
export function queueTarget(row: Record<string, unknown>): QueueTarget {
  const text = (key: string) => (typeof row[key] === 'string' && row[key] ? (row[key] as string) : null);
  return {
    workspaceId: isUuid(row.workspaceId) ? row.workspaceId : null,
    reservationId: isUuid(row.reservationId) ? row.reservationId : row.kind === 'reserve' && isUuid(row.id) ? row.id : null,
    estimatedUsdMicro: typeof row.estimatedUsdMicro === 'number' && Number.isFinite(row.estimatedUsdMicro) ? row.estimatedUsdMicro : null,
    provider: text('provider'),
    model: text('model'),
    at: text('at')
  };
}
