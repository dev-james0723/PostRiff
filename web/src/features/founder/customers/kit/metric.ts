import type { Coverage, DataState, MetricResult, MetricRow } from './types';

/**
 * Adapters from `POST /metrics/query` rows to what tiles, tables and charts render. Rows are pivoted and labelled,
 * never aggregated: a chart point with no row for a series gets `null` (a gap), not 0, and a tile shows the one
 * row the server returned for the whole interval. Comparison deltas appear only when the server sent them.
 */

export function isMeasured(row: Pick<MetricRow, 'dataState' | 'value'> | null | undefined): boolean {
  return Boolean(row) && row!.dataState === 'measured' && row!.value !== null && row!.value !== undefined;
}

/** The single state a set of rows is in: one state when they agree, `partial` when they do not, `unavailable` when empty. */
export function overallState(rows: readonly MetricRow[] | undefined): DataState {
  if (!rows || rows.length === 0) return 'unavailable';
  const states = new Set(rows.map((row) => row.dataState));
  return states.size === 1 ? rows[0].dataState : 'partial';
}

/**
 * The instant a not-yet-measurable metric started collecting, only when the adapter said so. A source watermark is the
 * last good read, not the instrumentation start, so it is never substituted here (see `lastGoodAt`).
 */
export function collectingSince(row: Pick<MetricRow, 'collectingSince'> | null | undefined): string | null {
  return row?.collectingSince ?? null;
}

/** The last good read the adapter recorded for the row's source, for "last good <date>" notes. */
export function lastGoodAt(row: Pick<MetricRow, 'sourceWatermark'> | null | undefined): string | null {
  return row?.sourceWatermark ?? null;
}

/** Rows without a time bucket (one per dimension combination) describe the whole interval. */
export function wholeIntervalRows(rows: readonly MetricRow[]): MetricRow[] {
  return rows.filter((row) => !row.interval?.start);
}

export function bucketRows(rows: readonly MetricRow[]): MetricRow[] {
  return rows.filter((row) => Boolean(row.interval?.start));
}

/** The one row for a metric over the whole interval, else the first row at all (a single-bucket answer). */
export function headlineRow(result: MetricResult | undefined, metricId?: string): MetricRow | null {
  if (!result) return null;
  const mine = metricId ? result.rows.filter((row) => row.metricId === metricId) : result.rows;
  if (mine.length === 0) return null;
  const whole = wholeIntervalRows(mine).find((row) => !row.dimensions || Object.keys(row.dimensions).length === 0);
  return whole ?? mine[0];
}

export interface TileInput {
  id: string;
  label: string;
  href?: string;
  period: string;
}

export interface TileData {
  id: string;
  label: string;
  value: number | null;
  unit: string;
  currency: string | null;
  delta: number | null;
  deltaPeriod: string | null;
  sparkline: Array<number | null>;
  dataState: DataState;
  coverage: Coverage | null;
  href?: string;
  receiptId: string | null;
  collectingSince: string | null;
  /** The source's last good read, kept apart from `collectingSince`. */
  lastGoodAt: string | null;
  reason: string | null;
}

/** The MetricTile props for one metric answer; the loading/error states are decided by the caller. */
export function tileFromResult(result: MetricResult | undefined, input: TileInput): TileData {
  const row = headlineRow(result, input.id);
  const sparkline = row?.sparkline ?? bucketRows(result?.rows ?? []).filter((bucket) => bucket.metricId === input.id && !hasDimensions(bucket)).map((bucket) => (isMeasured(bucket) ? bucket.value : null));
  return {
    id: input.id,
    label: input.label,
    value: row && isMeasured(row) ? row.value : null,
    unit: row?.unit ?? 'count',
    currency: row?.currency ?? null,
    delta: typeof row?.delta === 'number' ? row.delta : null,
    deltaPeriod: row?.deltaPeriod ?? (typeof row?.delta === 'number' ? input.period : null),
    sparkline,
    dataState: row?.dataState ?? 'unavailable',
    coverage: row?.coverage ?? null,
    href: input.href,
    receiptId: result?.queryReceiptId ?? null,
    collectingSince: collectingSince(row),
    lastGoodAt: lastGoodAt(row),
    reason: row?.reason ?? null
  };
}

function hasDimensions(row: MetricRow): boolean {
  return Boolean(row.dimensions && Object.keys(row.dimensions).length > 0);
}

export interface SeriesPoint {
  t: string;
  [seriesKey: string]: number | string | null;
}

export interface SeriesDescriptor {
  /** A CSS-safe key the chart config and data points use. */
  key: string;
  /** The dimension value (or the metric title when there is no dimension). */
  label: string;
  /** How many buckets of this series were measured; a series with none is drawn as gaps only. */
  measured: number;
}

export interface Series {
  points: SeriesPoint[];
  series: SeriesDescriptor[];
  unit: string;
  currency: string | null;
  dataState: DataState;
}

/**
 * Pivot time-bucketed rows into chart points: one point per bucket start, one key per series (a dimension value,
 * or the metric id when the rows carry no dimension). Missing buckets stay `null` so the chart shows a gap.
 */
export function seriesFromRows(rows: readonly MetricRow[], dimension?: string, labelFor: (row: MetricRow) => string = (row) => (dimension ? (row.dimensions?.[dimension] ?? 'unknown') : row.metricId)): Series {
  const buckets = bucketRows(rows);
  const keys = new Map<string, SeriesDescriptor>();
  const byTime = new Map<string, SeriesPoint>();
  for (const row of buckets) {
    const label = labelFor(row);
    let descriptor = keys.get(label);
    if (!descriptor) {
      descriptor = { key: `s${keys.size}`, label, measured: 0 };
      keys.set(label, descriptor);
    }
    const start = row.interval!.start;
    let point = byTime.get(start);
    if (!point) {
      point = { t: start };
      byTime.set(start, point);
    }
    if (isMeasured(row)) {
      point[descriptor.key] = row.value;
      descriptor.measured += 1;
    } else if (!(descriptor.key in point)) {
      point[descriptor.key] = null;
    }
  }
  const points = Array.from(byTime.values()).toSorted((a, b) => a.t.localeCompare(b.t));
  const first = buckets[0];
  return { points, series: Array.from(keys.values()), unit: first?.unit ?? 'count', currency: first?.currency ?? null, dataState: overallState(buckets) };
}

export interface CategoryItem {
  key: string;
  label: string;
  value: number | null;
  dataState: DataState;
  row: MetricRow;
}

/** Whole-interval rows grouped by one dimension, for bars and tables. Unmeasured rows keep `null`. */
export function categoriesFromRows(rows: readonly MetricRow[], dimension: string): CategoryItem[] {
  return wholeIntervalRows(rows)
    .filter((row) => row.dimensions && dimension in row.dimensions)
    .map((row, index) => ({ key: `c${index}`, label: row.dimensions![dimension], value: isMeasured(row) ? row.value : null, dataState: row.dataState, row }));
}

/** The coverage a server row carries, when it has one worth drawing (both parts known). */
export function knownUnknown(row: MetricRow | null | undefined): { known: number; unknown: number } | null {
  const coverage = row?.coverage;
  if (!coverage || typeof coverage.known !== 'number' || typeof coverage.unknown !== 'number') return null;
  return { known: coverage.known, unknown: coverage.unknown };
}
