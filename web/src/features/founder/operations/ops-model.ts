import type { PeriodKey } from '../customers/kit/period';
import type { DataState, MetricRow, Timestamp } from '../customers/kit/types';
import { timeValue } from '../customers/kit/format';

/**
 * Pure adapters behind Operations, Support and the Advanced data-health tab (CONTRACTS §8.D). Server metric rows are
 * picked, labelled, joined on their own dimension values and laid out; nothing is summed, averaged or re-rated here.
 * Every server row carries the query interval, so a row's day is `dimensions.window` — never `interval.start` — and a
 * row the server did not measure stays `null` (shown as "Unavailable"), never 0. No React here: the node test loads it.
 */

export const UNAVAILABLE = 'Unavailable';

/* ---------- the queries the pages send ---------- */

export type OpsQueryKey =
  | 'sourceHealth'
  | 'apiErrors'
  | 'apiLatency'
  | 'sloBurn'
  | 'queues'
  | 'connections'
  | 'publishRate'
  | 'publishOutcomes'
  | 'delivery'
  | 'calls'
  | 'supportOpen'
  | 'supportAging'
  | 'supportKinds'
  | 'supportSources';

export interface OpsMetricSpec {
  id: string;
  groupBy: readonly string[];
}

/**
 * Every metric query these pages send. Dimensions come from each metric's catalog `allowed_dimensions` and stay within
 * the schema's three (`tests/founder-ops.test.cjs` checks both against the catalog), so a 4xx from a page query is a
 * bug. No query asks for a comparison: a comparison with a `window` grouping is refused by the server.
 */
export const OPS_QUERIES: Record<OpsQueryKey, OpsMetricSpec> = {
  sourceHealth: { id: 'source_health', groupBy: ['source', 'state', 'reason'] },
  apiErrors: { id: 'api_error_rate', groupBy: ['route'] },
  apiLatency: { id: 'api_latency', groupBy: ['route'] },
  sloBurn: { id: 'slo_burn', groupBy: ['slo', 'burn_window'] },
  queues: { id: 'queue_health', groupBy: ['queue'] },
  connections: { id: 'connection_health', groupBy: ['provider', 'capability', 'state'] },
  publishRate: { id: 'publish_by_provider', groupBy: ['provider'] },
  publishOutcomes: { id: 'publish_outcomes', groupBy: ['platform', 'status'] },
  delivery: { id: 'notification_delivery', groupBy: ['channel', 'status'] },
  calls: { id: 'phone_calls', groupBy: ['state'] },
  supportOpen: { id: 'support_aging', groupBy: [] },
  supportAging: { id: 'support_aging', groupBy: ['age_band'] },
  supportKinds: { id: 'support_aging', groupBy: ['kind'] },
  supportSources: { id: 'support_aging', groupBy: ['source'] }
};

/** The kit `useMetric` input for one of the queries above (a fresh, mutable groupBy array). */
export function opsSpec(key: OpsQueryKey, period: PeriodKey): { id: string; period: PeriodKey; groupBy: string[] } {
  const spec = OPS_QUERIES[key];
  return { id: spec.id, period, groupBy: [...spec.groupBy] };
}

/* ---------- rows ---------- */

/** States whose value is a reading of the source (possibly qualified); anything else has no number to show. */
const VALUED: ReadonlySet<string> = new Set(['measured', 'partial', 'stale', 'synthetic', 'demo']);

/** The row's value when the server sent a reading, else null. A not-measured row is never read as 0. */
export function shownValue(row: Pick<MetricRow, 'value' | 'dataState'> | null | undefined): number | null {
  if (!row || !VALUED.has(String(row.dataState))) return null;
  return typeof row.value === 'number' && Number.isFinite(row.value) ? row.value : null;
}

export function dimension(row: Pick<MetricRow, 'dimensions'> | null | undefined, key: string): string | null {
  const value = row?.dimensions?.[key];
  return typeof value === 'string' && value !== '' ? value : null;
}

/** A numeric measure the server attached to the row (counts, peaks, ages), or null. */
export function measure(row: MetricRow | null | undefined, key: string): number | null {
  const measures = row?.measures as Record<string, unknown> | null | undefined;
  const value = measures?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function measureText(row: MetricRow | null | undefined, key: string): string | null {
  const measures = row?.measures as Record<string, unknown> | null | undefined;
  const value = measures?.[key];
  return typeof value === 'string' && value ? value : null;
}

export function measureFlag(row: MetricRow | null | undefined, key: string): boolean | null {
  const measures = row?.measures as Record<string, unknown> | null | undefined;
  const value = measures?.[key];
  return typeof value === 'boolean' ? value : null;
}

/** The kit `CategoryItem` shape for bars and tables: rows that carry `dim`, in the server's order. */
export interface DimensionItem {
  key: string;
  label: string;
  value: number | null;
  dataState: DataState;
  row: MetricRow;
}

export function byDimension(rows: readonly MetricRow[] | undefined, dim: string, labels: Record<string, string> = {}): DimensionItem[] {
  return (rows ?? [])
    .filter((row) => row.dimensions && dim in row.dimensions)
    .map((row, index) => {
      const raw = dimension(row, dim) ?? 'unknown';
      return { key: `${dim}-${index}`, label: labels[raw] ?? humanize(raw), value: shownValue(row), dataState: row.dataState, row };
    });
}

/** `items` in a fixed order of dimension values (e.g. age bands); values the order does not name follow in server order. */
export function inOrder(items: DimensionItem[], dim: string, order: readonly string[]): DimensionItem[] {
  const rank = (item: DimensionItem) => {
    const index = order.indexOf(dimension(item.row, dim) ?? '');
    return index === -1 ? order.length : index;
  };
  return items.map((item, index) => ({ item, index })).toSorted((a, b) => rank(a.item) - rank(b.item) || a.index - b.index).map(({ item }) => item);
}

export function humanize(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  return value.replaceAll('_', ' ');
}

/* ---------- formatting for the units these metrics use ---------- */

export function formatMs(value: number | null | undefined, openEnded = false): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNAVAILABLE;
  const text = value >= 1000 ? `${new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(value / 1000)} s` : `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value)} ms`;
  return openEnded ? `≥ ${text}` : text;
}

export function formatBurn(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNAVAILABLE;
  return `${new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(value)}×`;
}

export function formatRatio(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNAVAILABLE;
  return new Intl.NumberFormat('en', { style: 'percent', maximumFractionDigits: 2 }).format(value);
}

export function formatCount(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNAVAILABLE;
  return new Intl.NumberFormat('en').format(value);
}

/** Seconds as the largest sensible unit ("4 h", "2.5 d"); used for waiting time and source age. */
export function formatAge(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return UNAVAILABLE;
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86_400) return `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(seconds / 3600)} h`;
  return `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(seconds / 86_400)} d`;
}

/* ---------- API health: error rate and p50/p95 joined on the route ---------- */

export interface RouteHealth {
  route: string;
  requests: number | null;
  errorRate: number | null;
  serverErrors: number | null;
  clientErrors: number | null;
  p50: number | null;
  p95: number | null;
  p95OpenEnded: boolean;
  errorRow: MetricRow | null;
  p50Row: MetricRow | null;
  p95Row: MetricRow | null;
}

/** One line per route pattern: the server's error-rate row and its p50/p95 rows side by side, in the server's order. */
export function routeHealth(errorRows: readonly MetricRow[] | undefined, latencyRows: readonly MetricRow[] | undefined): RouteHealth[] {
  const routes = new Map<string, RouteHealth>();
  const entry = (route: string) => {
    let current = routes.get(route);
    if (!current) {
      current = { route, requests: null, errorRate: null, serverErrors: null, clientErrors: null, p50: null, p95: null, p95OpenEnded: false, errorRow: null, p50Row: null, p95Row: null };
      routes.set(route, current);
    }
    return current;
  };
  for (const row of errorRows ?? []) {
    const route = dimension(row, 'route');
    if (!route) continue;
    const current = entry(route);
    current.errorRow = row;
    current.errorRate = shownValue(row);
    current.requests = measure(row, 'requests');
    current.serverErrors = measure(row, 'serverErrors');
    current.clientErrors = measure(row, 'clientErrors');
  }
  for (const row of latencyRows ?? []) {
    const route = dimension(row, 'route');
    const percentile = dimension(row, 'percentile');
    if (!route || (percentile !== 'p50' && percentile !== 'p95')) continue;
    const current = entry(route);
    if (percentile === 'p50') {
      current.p50Row = row;
      current.p50 = shownValue(row);
    } else {
      current.p95Row = row;
      current.p95 = shownValue(row);
      current.p95OpenEnded = measureFlag(row, 'openEnded') === true;
    }
  }
  return [...routes.values()];
}

/* ---------- SLO burn (proposed 99.5%, not approved) ---------- */

export const BURN_WINDOWS = ['5m', '30m', '1h', '6h'] as const;
export const BURN_PAIRS = [
  { pair: '1h/5m', windows: ['1h', '5m'] },
  { pair: '6h/30m', windows: ['6h', '30m'] }
] as const;
export const SLO_LABELS: Record<string, string> = { api_availability: 'API availability', publish_success: 'Publishing success' };

export interface BurnWindowView {
  window: string;
  value: number | null;
  dataState: DataState;
  reason: string | null;
  total: number | null;
  bad: number | null;
  row: MetricRow;
}

export interface BurnPairView {
  pair: string;
  threshold: number | null;
  /** The server's verdict for the pair (both windows over the threshold with enough events). */
  alerting: boolean | null;
}

export interface BurnSloView {
  slo: string;
  label: string;
  windows: BurnWindowView[];
  pairs: BurnPairView[];
  /** The server's label for the target ("proposed SLO, not approved"). */
  sloLabel: string | null;
  /** The SLO had no measurable source (rows without a burn window). */
  unavailable: MetricRow | null;
}

export function burnBySlo(rows: readonly MetricRow[] | undefined): BurnSloView[] {
  const order: string[] = [];
  const bySlo = new Map<string, MetricRow[]>();
  for (const row of rows ?? []) {
    const slo = dimension(row, 'slo');
    if (!slo) continue;
    if (!bySlo.has(slo)) {
      bySlo.set(slo, []);
      order.push(slo);
    }
    bySlo.get(slo)!.push(row);
  }
  return order.map((slo) => {
    const sloRows = bySlo.get(slo)!;
    const windowed = new Map<string, MetricRow>(sloRows.filter((row) => dimension(row, 'burn_window')).map((row): [string, MetricRow] => [dimension(row, 'burn_window')!, row]));
    const windows = BURN_WINDOWS.filter((name) => windowed.has(name)).map((name) => {
      const row = windowed.get(name)!;
      return { window: name, value: shownValue(row), dataState: row.dataState, reason: row.reason ?? null, total: measure(row, 'total'), bad: measure(row, 'bad'), row };
    });
    const pairs = BURN_PAIRS.filter((pair) => pair.windows.some((name) => windowed.has(name))).map((pair) => {
      const row = pair.windows.map((name) => windowed.get(name)).find((candidate) => candidate !== undefined) ?? null;
      return { pair: pair.pair, threshold: measure(row, 'threshold'), alerting: measureFlag(row, 'alerting') };
    });
    const labelled = sloRows.find((row) => measureText(row, 'label'));
    return { slo, label: SLO_LABELS[slo] ?? humanize(slo), windows, pairs, sloLabel: measureText(labelled, 'label'), unavailable: windows.length === 0 ? sloRows[0] : null };
  });
}

/* ---------- queue health ---------- */

export const COUNTER_LABELS: Record<string, string> = {
  publicationUncertain: 'Publications in an uncertain state',
  queueDelayed: 'Publications overdue in the queue',
  publicationFailed: 'Failed publications',
  publicationHeld: 'Held publications',
  modelStuck: 'Writing runs stuck over 10 min',
  researchStuck: 'Research requests stuck over 10 min',
  costUnsettled: 'Cost reservations unsettled over 10 min',
  budgetStops: 'Budgets at their stop',
  budgetWarnings: 'Budgets past their warning',
  billingRejected24h: 'Billing events rejected (24 h)',
  notificationsUnsent: 'Legacy notices unsent over 10 min',
  notificationBacklog: 'Email/push deliveries overdue',
  notificationDead24h: 'Dead deliveries (24 h)',
  deletionPending: 'Account deletions pending',
  historyPurgesPending: 'Disconnect purges pending',
  metricReadsOverdue: 'Metric readings overdue',
  metricBackfillStale: 'Backfill readings stale',
  metricReadsDead24h: 'Dead metric readings (24 h)',
  historyImportsFailed24h: 'Failed history imports (24 h)',
  'sms.backlogOver10m': 'SMS overdue over 10 min',
  'sms.failedDeadUncertain24h': 'SMS failed, dead or uncertain (24 h)',
  'sms.suppressed24h': 'SMS suppressed (24 h)',
  'sms.quietDeferred': 'SMS deferred by quiet hours',
  'sms.acknowledgementCancelled24h': 'SMS cancelled by acknowledgement (24 h)',
  'sms.dispatches24h': 'SMS dispatched (24 h)',
  'sms.segments24h': 'SMS segments (24 h)',
  'sms.knownCostUsdMicro24h': 'SMS known cost, USD micro (24 h)'
};

export const QUEUE_LABELS: Record<string, string> = {
  publishing: 'Publishing',
  model_runs: 'Model runs',
  cost: 'Cost and budgets',
  billing: 'Billing',
  notifications: 'Notifications',
  privacy: 'Privacy obligations',
  growth: 'Growth readings',
  sms: 'SMS',
  other: 'Other'
};

export const QUEUE_ORDER = ['publishing', 'model_runs', 'notifications', 'sms', 'cost', 'billing', 'privacy', 'growth', 'other'];

export interface QueueCounterView {
  counter: string;
  label: string;
  peak: number | null;
  latest: number | null;
  latestAt: string | null;
  dataState: DataState;
  row: MetricRow;
}

export interface QueueGroupView {
  queue: string;
  label: string;
  counters: QueueCounterView[];
}

/** Rows of `queue_health` (one per counter) grouped by their queue; the peak is the row value, the latest a measure. */
export function queueGroups(rows: readonly MetricRow[] | undefined): QueueGroupView[] {
  const groups = new Map<string, QueueCounterView[]>();
  for (const row of rows ?? []) {
    const counter = dimension(row, 'counter');
    if (!counter) continue;
    const queue = dimension(row, 'queue') ?? 'other';
    if (!groups.has(queue)) groups.set(queue, []);
    groups.get(queue)!.push({ counter, label: COUNTER_LABELS[counter] ?? humanize(counter), peak: shownValue(row), latest: measure(row, 'latest'), latestAt: measureText(row, 'latestAt'), dataState: row.dataState, row });
  }
  const rank = (queue: string) => (QUEUE_ORDER.includes(queue) ? QUEUE_ORDER.indexOf(queue) : QUEUE_ORDER.length);
  return [...groups.entries()].toSorted((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0])).map(([queue, counters]) => ({ queue, label: QUEUE_LABELS[queue] ?? humanize(queue), counters }));
}

/* ---------- connection matrix (provider × capability) ---------- */

export const CONNECTION_STATES = ['blocked', 'expired', 'expiring', 'ok'] as const;
export type ConnectionState = (typeof CONNECTION_STATES)[number];
export const CAPABILITY_ORDER = ['identity', 'publish', 'schedule', 'analytics', 'comments_read', 'reply', 'moderate', 'media_types', 'webhooks'];

export interface MatrixCell {
  provider: string;
  capability: string;
  counts: Partial<Record<ConnectionState, number>>;
  /** The most serious state any connection in the cell is in (blocked → expired → expiring → ok). */
  worst: ConnectionState | null;
}

export interface ConnectionMatrix {
  providers: string[];
  capabilities: string[];
  cells: Record<string, MatrixCell>;
}

export function cellKey(provider: string, capability: string): string {
  return `${provider}|${capability}`;
}

/** `connection_health` rows (provider × capability × state → connections) pivoted into a grid; each count is a server row. */
export function connectionMatrix(rows: readonly MetricRow[] | undefined): ConnectionMatrix {
  const providers: string[] = [];
  const capabilities = new Set<string>();
  const cells: Record<string, MatrixCell> = {};
  for (const row of rows ?? []) {
    const provider = dimension(row, 'provider');
    const capability = dimension(row, 'capability');
    const state = dimension(row, 'state') as ConnectionState | null;
    const value = shownValue(row);
    if (!provider || !capability || !state || !(CONNECTION_STATES as readonly string[]).includes(state) || value === null) continue;
    if (!providers.includes(provider)) providers.push(provider);
    capabilities.add(capability);
    const key = cellKey(provider, capability);
    const cell = (cells[key] ??= { provider, capability, counts: {}, worst: null });
    cell.counts[state] = value;
  }
  for (const cell of Object.values(cells)) cell.worst = CONNECTION_STATES.find((state) => (cell.counts[state] ?? 0) > 0) ?? null;
  const ordered = [...capabilities].toSorted((a, b) => {
    const rank = (value: string) => (CAPABILITY_ORDER.includes(value) ? CAPABILITY_ORDER.indexOf(value) : CAPABILITY_ORDER.length);
    return rank(a) - rank(b) || a.localeCompare(b);
  });
  return { providers: providers.toSorted((a, b) => a.localeCompare(b)), capabilities: ordered, cells };
}

/* ---------- incidents: swimlanes by detector, and one timeline ---------- */

/** What the incident list sends in Live (`founder_incidents.public_incident`) and in Demo (the Demo scenario payload). */
export interface OpsIncident {
  id: string;
  detector?: string | null;
  detectorFamily?: string | null;
  scope?: string | null;
  severity?: string | null;
  state?: string | null;
  title?: string | null;
  openedAt?: Timestamp | null;
  observedAt?: Timestamp | null;
  acknowledgedAt?: Timestamp | null;
  resolvedAt?: Timestamp | null;
  affectedCount?: number | null;
  version?: number | null;
  events?: Array<{ id?: string; kind?: string; type?: string; at: Timestamp; body?: Record<string, unknown> | null }> | null;
  timeline?: Array<{ id?: string; kind?: string; type?: string; at: Timestamp; body?: Record<string, unknown> | null }> | null;
}

export interface TimelineEvent {
  kind: string;
  at: Timestamp;
  body: Record<string, unknown> | null;
}

export const DETECTOR_LABELS: Record<string, string> = {
  publish_failure_rate: 'Publishing failures',
  source_silence: 'Source silence',
  cost_anomaly: 'AI cost anomaly',
  payment_failure_spike: 'Payment failures',
  demo_publishing_outage: 'Publishing (Demo)',
  demo_cost_anomaly: 'AI cost (Demo)',
  demo_payment_exception: 'Payments (Demo)'
};
export const DETECTOR_ORDER = ['publish_failure_rate', 'source_silence', 'cost_anomaly', 'payment_failure_spike', 'demo_publishing_outage', 'demo_cost_anomaly', 'demo_payment_exception'];

export function detectorOf(incident: OpsIncident): string {
  return incident.detector ?? incident.detectorFamily ?? 'other';
}

/** The server's events (Live `events` with `kind`, Demo `timeline` with `type`) plus the lifecycle stamps, in time order. */
export function timelineEvents(incident: OpsIncident): TimelineEvent[] {
  const events: TimelineEvent[] = [...(incident.events ?? incident.timeline ?? [])]
    .map((event) => ({ kind: event.kind ?? event.type ?? 'event', at: event.at, body: event.body ?? null }));
  const has = (kind: string) => events.some((event) => event.kind === kind);
  const opened = incident.openedAt ?? incident.observedAt;
  if (opened !== null && opened !== undefined && !has('opened')) events.push({ kind: 'opened', at: opened, body: null });
  if (incident.acknowledgedAt && !has('acknowledged')) events.push({ kind: 'acknowledged', at: incident.acknowledgedAt, body: null });
  if (incident.resolvedAt && !has('resolved')) events.push({ kind: 'resolved', at: incident.resolvedAt, body: null });
  return events.filter((event) => timeValue(event.at) !== null).toSorted((a, b) => (timeValue(a.at) ?? 0) - (timeValue(b.at) ?? 0));
}

export function incidentStartMs(incident: OpsIncident): number | null {
  return timeValue(incident.openedAt) ?? timeValue(incident.observedAt) ?? timeValue(timelineEvents(incident)[0]?.at ?? null);
}

/** When the episode ended: its resolution stamp when resolved, `now` while it is still open. */
export function incidentEndMs(incident: OpsIncident, nowMs: number): number | null {
  if (incident.state !== 'resolved') return nowMs;
  const resolved = timeValue(incident.resolvedAt) ?? timeValue(timelineEvents(incident).findLast((event) => event.kind === 'resolved')?.at ?? null);
  return resolved ?? incidentStartMs(incident);
}

export interface SwimEpisode {
  id: string;
  incident: OpsIncident;
  severity: string;
  open: boolean;
  startMs: number;
  endMs: number;
  /** Geometry in percent of the window: where the bar starts and how wide it is. */
  left: number;
  width: number;
}

export interface SwimLane {
  detector: string;
  label: string;
  episodes: SwimEpisode[];
}

export const SWIMLANE_DAYS = 7;
const MIN_WIDTH = 1.2;

/** Episodes of the last `days` days in one lane per detector; a bar spans opened → resolved (or now while open). */
export function swimlanes(incidents: readonly OpsIncident[] | undefined, nowMs: number, days = SWIMLANE_DAYS): SwimLane[] {
  const span = days * 86_400_000;
  const windowStart = nowMs - span;
  const lanes = new Map<string, SwimEpisode[]>();
  for (const incident of incidents ?? []) {
    const startMs = incidentStartMs(incident);
    const endMs = incidentEndMs(incident, nowMs);
    if (startMs === null || endMs === null || endMs < windowStart || startMs > nowMs) continue;
    const from = Math.max(startMs, windowStart);
    const to = Math.min(Math.max(endMs, from), nowMs);
    const left = ((from - windowStart) / span) * 100;
    const width = Math.min(Math.max(((to - from) / span) * 100, MIN_WIDTH), 100 - Math.min(left, 100 - MIN_WIDTH));
    const detector = detectorOf(incident);
    if (!lanes.has(detector)) lanes.set(detector, []);
    lanes.get(detector)!.push({ id: incident.id, incident, severity: incident.severity ?? 'warning', open: incident.state !== 'resolved', startMs, endMs, left: Math.min(left, 100 - MIN_WIDTH), width });
  }
  const rank = (detector: string) => (DETECTOR_ORDER.includes(detector) ? DETECTOR_ORDER.indexOf(detector) : DETECTOR_ORDER.length);
  return [...lanes.entries()]
    .toSorted((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]))
    .map(([detector, episodes]) => ({ detector, label: DETECTOR_LABELS[detector] ?? humanize(detector), episodes: episodes.toSorted((a, b) => a.startMs - b.startMs) }));
}

/** Day boundaries for the swimlane axis: `days + 1` ticks from the window start to now, as epoch milliseconds. */
export function swimlaneTicks(nowMs: number, days = SWIMLANE_DAYS): number[] {
  return Array.from({ length: days + 1 }, (_, index) => nowMs - (days - index) * 86_400_000);
}

/* ---------- source health (every probed source) ---------- */

export const SOURCE_LABELS: Record<string, string> = {
  cron: 'Founder cron heartbeat',
  database: 'Consumer database', // copy-audit: allow — founder-only source health label
  control_database: 'Control database', // copy-audit: allow — founder-only source health label
  control_reader: 'Control reader role',
  phone_provider: 'Phone provider',
  notifications: 'Notification outbox',
  stripe_webhooks: 'Stripe webhooks',
  email_provider: 'Email provider (Resend)',
  model_gateway: 'Model settlements (gateway)'
};

export interface SourceView {
  source: string;
  label: string;
  state: DataState;
  /** The last good read the probe recorded (the source watermark). */
  lastGoodAt: string | null;
  /** Seconds since that read, as the server computed it. */
  ageSeconds: number | null;
  reason: string | null;
  row: MetricRow;
}

/** `source_health` rows (one per probed source, in the server's order) as list items. */
export function sourceViews(rows: readonly MetricRow[] | undefined): SourceView[] {
  return (rows ?? [])
    .filter((row) => dimension(row, 'source'))
    .map((row) => {
      const source = dimension(row, 'source')!;
      return { source, label: SOURCE_LABELS[source] ?? humanize(source), state: row.dataState, lastGoodAt: row.sourceWatermark ?? null, ageSeconds: typeof row.value === 'number' ? row.value : null, reason: row.reason ?? dimension(row, 'reason'), row };
    });
}

export function sourceTone(state: string): 'success' | 'warning' | 'danger' | 'neutral' {
  if (state === 'measured' || state === 'synthetic') return 'success';
  if (state === 'stale' || state === 'partial') return 'warning';
  if (state === 'unavailable') return 'danger';
  return 'neutral';
}

/* ---------- support ---------- */

export const AGE_BAND_ORDER = ['under_1d', '1d_to_3d', '3d_to_7d', '7d_to_14d', '14d_to_30d', 'over_30d'];
export const AGE_BAND_LABELS: Record<string, string> = {
  under_1d: 'Under 1 day',
  '1d_to_3d': '1–3 days',
  '3d_to_7d': '3–7 days',
  '7d_to_14d': '7–14 days',
  '14d_to_30d': '14–30 days',
  over_30d: 'Over 30 days'
};
export const REQUEST_KIND_LABELS: Record<string, string> = { export: 'Data export', deletion: 'Account deletion', diagnostics: 'Diagnostics', retraction: 'Retraction', billing: 'Billing', support: 'Support' };

/** Age bands in their natural order (the server returns them by name). */
export function ageBandItems(rows: readonly MetricRow[] | undefined): DimensionItem[] {
  return inOrder(byDimension(rows, 'age_band', AGE_BAND_LABELS), 'age_band', AGE_BAND_ORDER);
}

export interface TicketSourceView {
  /** The support-ticket source row exists and was collected (a ticket source has been chosen). */
  collected: boolean;
  reason: string | null;
  decision: string | null;
}

/** The support-ticket source as the server reports it (`support_aging` grouped by source), or null when not reported. */
export function ticketSource(rows: readonly MetricRow[] | undefined): TicketSourceView | null {
  const row = (rows ?? []).find((candidate) => dimension(candidate, 'source') === 'support_tickets');
  if (!row) return null;
  return { collected: row.dataState !== 'unavailable', reason: row.reason ?? null, decision: measureText(row, 'decision') };
}

/** The open data-request row of an ungrouped (or source-grouped) `support_aging` answer. */
export function openRequestsRow(rows: readonly MetricRow[] | undefined): MetricRow | null {
  return (rows ?? []).find((row) => (dimension(row, 'source') ?? 'data_requests') === 'data_requests') ?? null;
}
