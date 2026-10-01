import type { DataState, FounderMode, MetricResult, MetricRow } from '../customers/kit/types';
import type { Series, SeriesDescriptor, SeriesPoint } from '../customers/kit/metric';
import { count, stateLabel, tickDate, whenDate } from '../customers/kit/format';

/**
 * Pure adapters for the Product page (CONTRACTS §8.C; PRD §5.3, §7.2): rows from `POST /metrics/query` and the
 * `GET /product/funnel/stuck` drill-down, labelled and arranged for display. Nothing is summed, averaged or derived:
 * conversions, drop-offs, medians, shares and cell ratios are the server's own values, and a value the server did not
 * measure stays `null` so the page says why instead of drawing a zero. Every server row carries the query interval, so
 * these adapters key on dimensions (`step`, `feature`, `cohort`/`week`, `confidence`, `window`), never on the interval.
 */

/* ---------- shared row readers ---------- */

/** States whose value is shown as a number (Demo rows are `synthetic`). Anything else explains itself. */
const SHOWN_STATES = new Set<DataState>(['measured', 'partial', 'stale', 'synthetic', 'demo']);

export function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

/** The server's value when its state allows showing one; otherwise null (never 0). */
export function shownValue(row: Pick<MetricRow, 'value' | 'dataState'> | null | undefined): number | null {
  if (!row || !SHOWN_STATES.has(row.dataState)) return null;
  return finite(row.value);
}

export function measuresOf(row: MetricRow | null | undefined): Record<string, unknown> {
  const raw = row?.measures;
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
}

/** A dimension value as text: the retention `week` arrives as a number. */
export function dimension(row: MetricRow, name: string): string | null {
  const value = row.dimensions?.[name] as unknown;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return text(value);
}

/**
 * The row that describes a whole answer when the server could not break it down: a single row without the expected
 * dimension (`insufficient_history`, `not_instrumented`, `demo_not_simulated`, `source_not_configured`).
 */
export function statusRow(result: MetricResult | undefined, dimensionName: string): MetricRow | null {
  const rows = result?.rows ?? [];
  if (rows.length === 0) return null;
  return rows.some((row) => dimension(row, dimensionName) !== null) ? null : rows[0];
}

export interface HistoryNeed {
  availableDays: number;
  requiredDays: number;
}

export function historyOf(row: MetricRow | null | undefined): HistoryNeed | null {
  const raw = row?.history as unknown;
  if (!raw || typeof raw !== 'object') return null;
  const { availableDays, requiredDays } = raw as Record<string, unknown>;
  const available = finite(availableDays);
  const required = finite(requiredDays);
  return available !== null && required !== null ? { availableDays: available, requiredDays: required } : null;
}

/** Fixed copy for every reason these definitions return; an unknown reason is shown as its words. */
export function reasonText(reason: string | null | undefined, row?: MetricRow | null): string | null {
  if (!reason) return null;
  const history = historyOf(row);
  const measures = measuresOf(row ?? null);
  switch (reason) {
    case 'not_instrumented':
      return 'Not instrumented yet.';
    case 'collecting_since_after_cohort_start':
      return row?.collectingSince ? `Collecting since ${whenDate(row.collectingSince)}, after this cohort signed up.` : 'Collection started after this cohort signed up.';
    case 'collecting_since_after_interval_start':
      return row?.collectingSince ? `Collecting since ${whenDate(row.collectingSince)}, inside this period.` : 'Collection started inside this period.';
    case 'transition_proxy':
      return 'Partly from a transition proxy, a lower bound.';
    case 'no_matured_workspaces':
      return 'No signup in this period is 14 days old yet.';
    case 'no_first_value_in_window':
      return 'No workspace in this cohort reached a first value within 14 days.';
    case 'no_active_workspaces':
      return 'No active workspaces in this period, so there is no eligible denominator.';
    case 'insufficient_history':
      return history ? `Needs ${count(history.requiredDays)} days of history; ${count(history.availableDays)} available.` : 'Needs more history than exists.';
    case 'sample_too_small': {
      const minimum = finite(measures.minimumGroup);
      return minimum !== null ? `Too few workspaces: each group needs at least ${count(minimum)}.` : 'Too few workspaces to compare.';
    }
    case 'cell_not_matured':
      return 'This week has not finished yet.';
    case 'empty_cohort':
      return 'No signups in this cohort.';
    case 'demo_not_simulated':
      return 'Not simulated in the Demo dataset.';
    case 'source_not_configured':
      return 'Source not configured.';
    case 'source_stale':
      return 'Source is stale.';
    case 'definition_not_activated':
      return 'Definition not activated.';
    default:
      return `${stateLabel(reason)}.`;
  }
}

/* ---------- activation funnel (M23) ---------- */

/** The definition's steps in order (founder_metrics_product.STEPS); the first is the cohort anchor. */
export const FUNNEL_STEPS = ['workspace_created', 'channel_connected', 'voice_activated', 'draft_created', 'draft_approved', 'post_scheduled', 'publish_verified'] as const;
export type FunnelStepId = (typeof FUNNEL_STEPS)[number];

export const STEP_LABEL: Record<FunnelStepId, string> = {
  workspace_created: 'Signed up',
  channel_connected: 'Connected a channel',
  voice_activated: 'Set up a voice',
  draft_created: 'Created a first draft',
  draft_approved: 'Approved a draft',
  post_scheduled: 'Scheduled a post',
  publish_verified: 'Verified a publish'
};

export function stepLabel(step: string): string {
  return (STEP_LABEL as Record<string, string>)[step] ?? stateLabel(step);
}

export interface MetricIntervalLike {
  start: string;
  end: string;
  timeZone: string;
}

export interface FunnelStep {
  id: string;
  label: string;
  order: number;
  /** Workspaces that reached the step (server count), or null when the step is not measured. */
  reached: number | null;
  /** The step's denominator: the matured cohort, or the part of it the taxonomy covered. */
  of: number | null;
  /** The server's conversion from signup. */
  rate: number | null;
  /** The server's drop from the previous step's rate, in rate units. */
  drop: number | null;
  /** Workspaces that reached the previous step but not this one (same rule as the drill-down route). */
  stuck: number | null;
  /** Cohort workspaces the taxonomy did not observe for this step. */
  unknown: number | null;
  immature: number | null;
  windowDays: number | null;
  source: string | null;
  proxy: string | null;
  dataState: DataState;
  reason: string | null;
  collectingSince: string | null;
  interval: MetricIntervalLike | null;
  row: MetricRow;
}

function intervalOf(row: MetricRow): MetricIntervalLike | null {
  const raw = row.interval as unknown;
  if (!raw || typeof raw !== 'object') return null;
  const { start, end, timeZone } = raw as Record<string, unknown>;
  return typeof start === 'string' && typeof end === 'string' && typeof timeZone === 'string' ? { start, end, timeZone } : null;
}

/** The funnel's steps in the server's order (`measures.order`), unknown steps last. */
export function funnelSteps(rows: readonly MetricRow[] | undefined): FunnelStep[] {
  const known = FUNNEL_STEPS as readonly string[];
  const steps = (rows ?? [])
    .filter((row) => row.metricId === 'activation_funnel' && dimension(row, 'step') !== null && dimension(row, 'cohort') === null)
    .map((row): FunnelStep => {
      const id = dimension(row, 'step') as string;
      const measures = measuresOf(row);
      const reached = shownValue(row);
      const order = finite(measures.order) ?? (known.includes(id) ? known.indexOf(id) + 1 : known.length + 1);
      return {
        id,
        label: stepLabel(id),
        order,
        reached,
        of: reached === null ? null : finite(row.coverage?.denominator),
        rate: reached === null ? null : finite(measures.rate),
        drop: reached === null ? null : finite(measures.dropFromPrevious),
        stuck: reached === null ? null : finite(measures.stuckFromPrevious),
        unknown: finite(row.coverage?.unknown),
        immature: finite(measures.immature),
        windowDays: finite(measures.windowDays),
        source: text(measures.source),
        proxy: text(measures.proxy),
        dataState: row.dataState,
        reason: row.reason ?? null,
        collectingSince: row.collectingSince ?? null,
        interval: intervalOf(row),
        row
      };
    });
  return steps.toSorted((a, b) => a.order - b.order);
}

/** A step can open its stuck list when the server counted workspaces stuck before it. */
export function canDrillStuck(step: FunnelStep): boolean {
  return step.order > 1 && step.stuck !== null && step.stuck > 0 && step.interval !== null && step.reached !== null;
}

export function sourceLabel(source: string | null | undefined): string | null {
  switch (source) {
    case 'workspace_start':
      return 'Workspace start';
    case 'taxonomy':
      return 'Product events';
    case 'transition_proxy':
      return 'Transition proxy';
    case 'taxonomy+transition_proxy':
      return 'Product events + proxy';
    case null:
    case undefined:
    case '':
      return null;
    default:
      return stateLabel(source);
  }
}

/** A rate difference in percentage points, as written: `12.3 pts`. Formatting only (×100 for display). */
export function points(value: number | null | undefined): string | null {
  const number = finite(value);
  if (number === null) return null;
  return `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(Math.abs(number) * 100)} pts`;
}

/** A signed difference in percentage points (`+8 pts`, `−3.1 pts`, `0 pts`). Formatting only. */
export function signedPoints(value: number | null | undefined): string | null {
  const number = finite(value);
  if (number === null) return null;
  const sign = number > 0 ? '+' : number < 0 ? '−' : '';
  return `${sign}${points(number)}`;
}

/** A bar width for a server ratio: geometry only, clamped to the track. */
export function barWidth(share: number | null | undefined): string {
  const number = finite(share);
  if (number === null) return '0%';
  return `${Math.min(100, Math.max(0, number * 100))}%`;
}

/* ---------- stuck workspaces (GET /product/funnel/stuck) ---------- */

export interface StuckWorkspace {
  workspaceId: string;
  name: string | null;
  plan: string | null;
  status: string | null;
  createdAt: string | null;
}

export interface StuckData {
  mode: FounderMode;
  step: string;
  previousStep: string;
  interval: MetricIntervalLike;
  limit: number;
  windowDays: number;
  source: string;
  rows: StuckWorkspace[];
  truncated: boolean;
  reason?: string;
}

/** Capabilities the route checks (founder_metrics_product.stuck_workspaces); asked for only when the operator holds them. */
export function canListStuck(capabilities: readonly string[], mode: FounderMode): boolean {
  const needed = ['customers.read', 'metrics.query', ...(mode === 'live' ? ['workspaces.read'] : [])];
  return needed.every((capability) => capabilities.includes(capability));
}

export function stuckPath(mode: FounderMode, step: string, interval: MetricIntervalLike): string {
  const params = new URLSearchParams({ mode, step, start: interval.start, end: interval.end, timeZone: interval.timeZone });
  return `/product/funnel/stuck?${params.toString()}`;
}

/** The answer must be for the mode and step asked, with a row list; anything else is not shown. */
export function verifyStuck(data: unknown, mode: FounderMode, step: string): StuckData {
  const value = data as Partial<StuckData> | null;
  if (!value || value.mode !== mode || value.step !== step || !Array.isArray(value.rows) || typeof value.truncated !== 'boolean') {
    throw new Error('The stuck-workspace list could not be verified. Retry.');
  }
  return value as StuckData;
}

/* ---------- time to value ---------- */

export interface TimeToValue {
  /** Median seconds from signup to first value (server), or null. */
  median: number | null;
  n: number | null;
  cohort: number | null;
  noFirstValue: number | null;
  immature: number | null;
  p25: number | null;
  p75: number | null;
  windowDays: number | null;
  dataState: DataState;
  reason: string | null;
  row: MetricRow;
}

export function timeToValue(result: MetricResult | undefined): TimeToValue | null {
  const row = (result?.rows ?? []).find((item) => item.metricId === 'time_to_value' && dimension(item, 'cohort') === null) ?? null;
  if (!row) return null;
  const measures = measuresOf(row);
  const median = shownValue(row);
  return {
    median,
    n: finite(measures.n),
    cohort: finite(measures.cohort),
    noFirstValue: finite(measures.noFirstValue),
    immature: finite(measures.immature),
    p25: median === null ? null : finite(measures.p25),
    p75: median === null ? null : finite(measures.p75),
    windowDays: finite(measures.windowDays),
    dataState: row.dataState,
    reason: row.reason ?? null,
    row
  };
}

/* ---------- feature adoption ---------- */

export const FEATURE_LABEL: Record<string, string> = {
  voice: 'Voice',
  brand: 'Brand kit',
  write_like_me: 'Write like me',
  quick_start: 'Quick start',
  agent_drafting: 'Agent drafting',
  review: 'Review and approve',
  scheduling: 'Scheduling',
  publishing: 'Publishing',
  campaigns: 'Campaigns',
  automations: 'Automations',
  suggestions: 'Suggestions',
  research: 'Research',
  humanizer: 'Humanizer',
  weekly_operator: 'Weekly operator'
};

export function featureLabel(feature: string): string {
  return FEATURE_LABEL[feature] ?? stateLabel(feature);
}

export interface AdoptionItem {
  feature: string;
  label: string;
  share: number | null;
  adopters: number | null;
  eligible: number | null;
  source: string | null;
  dataState: DataState;
  reason: string | null;
  collectingSince: string | null;
  row: MetricRow;
}

export function adoptionItems(rows: readonly MetricRow[] | undefined): AdoptionItem[] {
  return (rows ?? [])
    .filter((row) => row.metricId === 'feature_adoption' && dimension(row, 'feature') !== null)
    .map((row) => {
      const feature = dimension(row, 'feature') as string;
      const measures = measuresOf(row);
      const share = shownValue(row);
      return {
        feature,
        label: featureLabel(feature),
        share,
        adopters: share === null ? null : (finite(row.coverage?.numerator) ?? finite(measures.adopters)),
        eligible: finite(row.coverage?.denominator) ?? finite(measures.eligible),
        source: text(measures.source),
        dataState: row.dataState,
        reason: row.reason ?? null,
        collectingSince: row.collectingSince ?? null,
        row
      };
    });
}

/** The eligible-workspace denominator the server used (the same for every feature in one answer). */
export function eligibleWorkspaces(items: readonly AdoptionItem[]): number | null {
  return items.find((item) => item.eligible !== null)?.eligible ?? null;
}

/* ---------- weekly retention ---------- */

export interface RetentionCell {
  week: number;
  share: number | null;
  retained: number | null;
  size: number | null;
  matured: boolean;
  dataState: DataState;
  reason: string | null;
}

export interface RetentionCohort {
  cohort: string;
  label: string;
  size: number | null;
  cells: RetentionCell[];
}

export interface RetentionGrid {
  weeks: number[];
  cohorts: RetentionCohort[];
}

export function retentionGrid(rows: readonly MetricRow[] | undefined): RetentionGrid {
  const cohorts = new Map<string, RetentionCohort>();
  const weeks = new Set<number>();
  for (const row of rows ?? []) {
    if (row.metricId !== 'retention_weekly') continue;
    const cohort = dimension(row, 'cohort');
    const rawWeek = dimension(row, 'week');
    const week = rawWeek === null ? null : finite(Number(rawWeek));
    if (cohort === null || week === null) continue;
    weeks.add(week);
    let entry = cohorts.get(cohort);
    if (!entry) {
      entry = { cohort, label: tickDate(cohort), size: null, cells: [] };
      cohorts.set(cohort, entry);
    }
    const size = finite(row.coverage?.denominator);
    if (entry.size === null && size !== null) entry.size = size;
    const share = shownValue(row);
    entry.cells.push({
      week,
      share,
      retained: share === null ? null : finite(row.coverage?.numerator),
      size,
      matured: row.reason !== 'cell_not_matured',
      dataState: row.dataState,
      reason: row.reason ?? null
    });
  }
  const ordered = Array.from(weeks).toSorted((a, b) => a - b);
  return { weeks: ordered, cohorts: Array.from(cohorts.values()).map((entry) => ({ ...entry, cells: entry.cells.toSorted((a, b) => a.week - b.week) })) };
}

/** A cell's swatch strength: geometry from the server's share, a floor so a 0% cell still reads as measured. */
export function cellOpacity(share: number | null): number {
  if (share === null) return 0;
  return Math.round((0.12 + 0.88 * Math.min(1, Math.max(0, share))) * 100) / 100;
}

/* ---------- time back by confidence (M24) ---------- */

/** Fixed order and colour slot per confidence; the three are never added together. */
export const CONFIDENCES = ['measured', 'personalized', 'estimated'] as const;
export type Confidence = (typeof CONFIDENCES)[number];

export const CONFIDENCE_LABEL: Record<Confidence, string> = { measured: 'Measured', personalized: 'Personalized', estimated: 'Estimated' };

export const CONFIDENCE_HINT: Record<Confidence, string> = {
  measured: 'Active time recorded on the task',
  personalized: "The person's own baseline",
  estimated: "Rafii's default baseline"
};

/** The chart token for a confidence, matching the kit chart's palette slot for its series index. */
export function confidenceColor(confidence: Confidence): string {
  return `var(--chart-${CONFIDENCES.indexOf(confidence) + 1})`;
}

export interface ConfidenceTotal {
  confidence: Confidence;
  label: string;
  seconds: number | null;
  tasks: number | null;
  dataState: DataState | null;
  reason: string | null;
}

/** One entry per confidence, in the fixed order; a confidence without a row says so (null), never 0. */
export function timeBackTotals(rows: readonly MetricRow[] | undefined): ConfidenceTotal[] {
  const byConfidence = new Map<string, MetricRow>();
  for (const row of rows ?? []) {
    const confidence = dimension(row, 'confidence');
    if (row.metricId === 'time_back' && confidence !== null && dimension(row, 'window') === null && !byConfidence.has(confidence)) byConfidence.set(confidence, row);
  }
  return CONFIDENCES.map((confidence) => {
    const row = byConfidence.get(confidence) ?? null;
    const seconds = shownValue(row);
    return {
      confidence,
      label: CONFIDENCE_LABEL[confidence],
      seconds,
      tasks: seconds === null ? null : finite(row?.sampleCount),
      dataState: row?.dataState ?? null,
      reason: row?.reason ?? null
    };
  });
}

/**
 * Daily rows (`window` × `confidence`) as a chart series with the three confidences always present in the same order,
 * so each keeps its colour. A day without a row for a confidence is a gap (null).
 */
export function timeBackSeries(rows: readonly MetricRow[] | undefined): Series {
  return windowSeries(rows, { by: 'confidence', order: CONFIDENCES, fixed: true, labelFor: (value) => (CONFIDENCE_LABEL as Record<string, string>)[value] ?? stateLabel(value) });
}

/* ---------- daily series by the `window` dimension ---------- */

export interface WindowSeriesOptions {
  /** The dimension that splits series; without it, one series named `label`. */
  by?: string;
  /** Series order (and so colour slots); values not listed follow in the order they arrive. */
  order?: readonly string[];
  /** Keep every `order` entry as a series even when no row has it, so colours never shift. */
  fixed?: boolean;
  labelFor?: (value: string) => string;
  /** The single series' label when `by` is not given. */
  label?: string;
}

/**
 * Pivot rows bucketed by the `window` dimension (a local day, `YYYY-MM-DD`) into chart points: one point per day, one
 * series per value of `by` (or a single series). Missing days and unmeasured rows stay null so the chart shows a gap.
 */
export function windowSeries(rows: readonly MetricRow[] | undefined, options: WindowSeriesOptions = {}): Series {
  const { by, order = [], fixed = false, labelFor = stateLabel, label } = options;
  const bucketed = (rows ?? []).filter((row) => dimension(row, 'window') !== null);
  const keyOf = (row: MetricRow) => (by ? (dimension(row, by) ?? 'unknown') : row.metricId);
  const values = Array.from(new Set(bucketed.map(keyOf)));
  const ordered = [...order.filter((value) => fixed || values.includes(value)), ...values.filter((value) => !order.includes(value))];
  const descriptors = new Map<string, SeriesDescriptor>(ordered.map((value, index) => [value, { key: `s${index}`, label: by ? labelFor(value) : (label ?? value), measured: 0 }]));
  const points = new Map<string, SeriesPoint>();
  for (const row of bucketed) {
    const day = dimension(row, 'window') as string;
    const descriptor = descriptors.get(keyOf(row)) as SeriesDescriptor;
    let point = points.get(day);
    if (!point) {
      point = { t: day };
      for (const item of descriptors.values()) point[item.key] = null;
      points.set(day, point);
    }
    const value = shownValue(row);
    if (value !== null) {
      point[descriptor.key] = value;
      descriptor.measured += 1;
    }
  }
  const first = bucketed[0];
  const states = new Set(bucketed.map((row) => row.dataState));
  return {
    points: Array.from(points.values()).toSorted((a, b) => a.t.localeCompare(b.t)),
    series: Array.from(descriptors.values()),
    unit: first?.unit ?? 'count',
    currency: first?.currency ?? null,
    dataState: bucketed.length === 0 ? 'unavailable' : states.size === 1 ? bucketed[0].dataState : 'partial'
  };
}

/* ---------- retention correlations (P2 hypothesis) ---------- */

export interface CorrelationItem {
  feature: string;
  label: string;
  adopters: number | null;
  adoptersRetained: number | null;
  adopterShare: number | null;
  nonAdopters: number | null;
  nonAdoptersRetained: number | null;
  nonAdopterShare: number | null;
  difference: number | null;
  basis: string | null;
  dataState: DataState;
  reason: string | null;
  row: MetricRow;
}

export function correlationItems(rows: readonly MetricRow[] | undefined): CorrelationItem[] {
  return (rows ?? [])
    .filter((row) => row.metricId === 'retention_correlations' && dimension(row, 'feature') !== null)
    .map((row) => {
      const feature = dimension(row, 'feature') as string;
      const measures = measuresOf(row);
      const share = shownValue(row);
      const compared = share !== null;
      return {
        feature,
        label: featureLabel(feature),
        adopters: compared ? finite(measures.adopters) : null,
        adoptersRetained: compared ? finite(measures.adoptersRetained) : null,
        adopterShare: share,
        nonAdopters: compared ? finite(measures.nonAdopters) : null,
        nonAdoptersRetained: compared ? finite(measures.nonAdoptersRetained) : null,
        nonAdopterShare: compared ? finite(measures.nonAdopterShare) : null,
        difference: compared ? finite(measures.difference) : null,
        basis: text(measures.basis),
        dataState: row.dataState,
        reason: row.reason ?? null,
        row
      };
    });
}

/** Whether an answer is labelled a hypothesis by the server (every correlations row is). */
export function isHypothesis(result: MetricResult | undefined): boolean {
  return (result?.rows ?? []).some((row) => measuresOf(row).basis === 'hypothesis');
}
