/**
 * Browser-side mirror of the founder admin API (docs/design/founder-admin/CONTRACTS.md §3–§5). Every payload arrives
 * inside the control envelope; numbers are server values with their unit and coverage, never recomputed here.
 */
import type { AgentResult } from '@/lib/agent-runtime/types';
import type { PageOutlineItem } from '@/lib/site-agent/types';

/** Demo is a data mode (`?mode=demo`); the environment is where the deployment runs. Never mixed in copy. */
export type FounderMode = 'live' | 'demo';
export type FounderEnvironment = 'local' | 'staging' | 'production';
export const FOUNDER_MODES: readonly FounderMode[] = ['live', 'demo'];

/**
 * `measured` is the only state a number is shown for as-is. `collecting`: instrumented from a date, nothing measured
 * yet ("collecting since <date>"); `synthetic`: Demo data; `suppressed`: withheld by policy. Kept open so the Live
 * adapters' states stay assignable as they land.
 */
export type DataState = 'measured' | 'partial' | 'stale' | 'unavailable' | 'collecting' | 'synthetic' | 'suppressed' | 'demo' | (string & {});

export interface Envelope<T> {
  requestId: string;
  environment: FounderEnvironment;
  asOf: string;
  dataState: DataState;
  receiptIds: string[];
  data: T;
}

export interface FounderSession {
  assurance: 'aal2';
  capabilities: string[];
  csrfToken: string;
}

export interface Coverage {
  known?: number | null;
  unknown?: number | null;
  numerator?: number | null;
  denominator?: number | null;
  [key: string]: unknown;
}

export interface SeriesPoint {
  /** ISO date or timestamp of the bucket start. */
  t: string;
  value: number | null;
}

/* ---------- GET /overview ---------- */

export interface PulseTile {
  id: string;
  label: string;
  value: number | null;
  unit: string;
  currency?: string | null;
  delta?: number | null;
  deltaPeriod?: string | null;
  /** 30 points as the server bucketed them: plain values, or `{t, value}` points. `null` is a gap, never zero. */
  sparkline: SeriesPoint[] | Array<number | null>;
  dataState: DataState;
  coverage?: Coverage | null;
  receiptId?: string | null;
  href: string;
  /** When `dataState` is `collecting`: the date instrumentation started. */
  collectingSince?: string | null;
  definition?: string | null;
  reason?: string | null;
  /** A short qualifier the definition attaches to the value, e.g. "Candidate v2 catalog (not active)" on the Demo MRR. */
  note?: string | null;
}

export type AttentionSeverity = 'info' | 'warning' | 'critical';

export interface AttentionAction {
  id: string;
  label: string;
  /** `explain` and `draft_reminder` open Rafii with a prompt; `open` follows `href`; `ack` acknowledges an incident version. */
  kind: 'explain' | 'open' | 'draft_reminder' | 'ack' | string;
  href?: string | null;
  prompt?: string | null;
  incidentId?: string | null;
  version?: number | null;
}

export interface AttentionItem {
  id: string;
  severity: AttentionSeverity;
  title: string;
  scope: string;
  count: number | null;
  since: string | null;
  href: string;
  /** The server sends action objects (CONTRACTS §3); a bare kind string is read as `{id: kind, kind}` by `attention.ts`. */
  actions: Array<AttentionAction | string>;
  receiptId?: string | null;
}

/** An item whose actions are all objects, as `normalizeAttentionItem` leaves them. */
export type NormalizedAttentionItem = Omit<AttentionItem, 'actions'> & { actions: AttentionAction[] };

export interface TrendSeries {
  id: string;
  label: string;
  unit: string;
  currency?: string | null;
  points: SeriesPoint[];
  dataState?: DataState;
  receiptId?: string | null;
}

export interface OverviewTrend {
  id: string;
  title: string;
  period: string;
  unit?: string;
  currency?: string | null;
  series: TrendSeries[];
  receiptId?: string | null;
  /** Every receipt behind the chart (one per series). */
  receiptIds?: string[];
  dataState: DataState;
  coverage?: Coverage | null;
  definition?: string | null;
  href?: string | null;
}

export type SourceState = 'measured' | 'stale' | 'unavailable' | 'partial' | 'unknown';

export interface SourceHealth {
  sourceId: string;
  label?: string | null;
  state: SourceState;
  lastGoodAt: string | null;
  reasonCode: string | null;
}

export interface OverviewBrief {
  text: string;
  receiptIds: string[];
  generatedAt?: string | null;
}

export interface Overview {
  pulse: PulseTile[];
  attention: AttentionItem[];
  timeZone?: string;
  trends: { revenueVsCost: OverviewTrend | null; activeVsPublish: OverviewTrend | null };
  sourceHealth: SourceHealth[];
  brief: OverviewBrief | null;
}

export type OverviewPeriod = '7d' | '30d' | '90d';
export const OVERVIEW_PERIODS: readonly OverviewPeriod[] = ['7d', '30d', '90d'];

/* ---------- POST /metrics/query and receipts ---------- */

export interface MetricInterval {
  start: string;
  end: string;
  timeZone?: string;
}

/** The `MetricQuery` DSL body (`QueryService.metric_query`): half-open interval, ≤1000 points, server-chosen grain. */
export interface MetricQueryBody {
  metricIds: string[];
  interval: Required<MetricInterval>;
  groupBy: string[];
  filters: Array<{ dimension: string; operator: 'eq' | 'in'; values: string[] }>;
  comparison: 'none' | 'previous_equal_elapsed' | 'previous_complete' | 'cohort_age_aligned';
  limit: number;
}

export interface MetricRow {
  metricId: string;
  definitionVersion: string | number;
  interval?: MetricInterval | null;
  dimensions?: Record<string, string> | null;
  value: number | null;
  unit: string;
  currency?: string | null;
  dataState: DataState;
  coverage?: Coverage | null;
  sourceWatermark?: string | null;
  reason?: string | null;
  collectingSince?: string | null;
  /** History a definition still needs before it can be measured (reason `insufficient_history`). */
  history?: { availableDays: number; requiredDays: number } | null;
  delta?: number | null;
  deltaPeriod?: string | null;
  sparkline?: Array<number | null> | null;
  [key: string]: unknown;
}

/** `POST /metrics/query` answers with the receipt body itself, not the standard envelope (`http.py`). */
export interface MetricQueryResult {
  requestId: string;
  queryReceiptId: string;
  asOf: string;
  dataState: DataState;
  rows: MetricRow[];
  executionState?: string;
  coverage?: Record<string, unknown>;
  warnings?: string[];
  [key: string]: unknown;
}

/** A stored query receipt; the store writes camelCase, older rows read back snake_case, so the drawer accepts both. */
export type MetricReceipt = Record<string, unknown> & { id: string };

/* ---------- Demo workspace (scenario + revision) ---------- */

export interface FounderWorkspaceData {
  mode: FounderMode;
  revision: number;
  scenario?: string | { id?: string; key?: string };
  summary?: Record<string, unknown>;
  receipt?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DemoActionBody {
  action: string;
  targetId: string;
  value: string;
  revision: number;
  requestId: string;
}

export interface DemoActionResult {
  mode: FounderMode;
  revision: number;
  [key: string]: unknown;
}

export const DEMO_SCENARIOS = [
  ['normal', 'Normal operation'],
  ['payment_failure', 'Payment failure'],
  ['outage', 'Bug / outage'],
  ['stale_data', 'Stale data'],
  ['notification_failure', 'Notification failure'],
  ['cost_anomaly', 'Cost anomaly'],
  ['recovery', 'Recovery']
] as const;

/* ---------- incidents / follow-ups / contact / schedules ---------- */

/**
 * A server timestamp. Metrics and follow-ups write ISO 8601 strings; the founder record modules (incidents, contact
 * policy, schedules) write epoch seconds. The format helpers read both; pages never compare these as strings.
 */
export type Timestamp = string | number;

export type IncidentSeverity = 'warning' | 'critical';
export type IncidentState = 'open' | 'acknowledged' | 'investigating' | 'mitigated' | 'resolved';

export interface FounderIncident {
  id: string;
  environment: FounderEnvironment;
  detector: string;
  scope: string;
  episodeKey?: string;
  severity: IncidentSeverity;
  state: IncidentState;
  openedAt: Timestamp;
  acknowledgedAt: Timestamp | null;
  resolvedAt: Timestamp | null;
  evidence: Record<string, unknown>;
  affectedCount: number;
  version: number;
  title?: string | null;
  events?: { id: string; kind: string; at: Timestamp; body?: Record<string, unknown> }[];
}

export type FollowUpState = 'draft' | 'scheduled' | 'due' | 'completed' | 'cancelled' | 'missed';

export interface FounderFollowUp {
  id: string;
  sourceType: string;
  sourceId: string;
  title: string;
  dueAt: string | null;
  timeZone: string;
  state: FollowUpState;
  evidence: Record<string, unknown>;
  revision: number;
  createdAt: string;
  updatedAt: string;
}

export interface FollowUpWriteBody {
  sourceType?: string;
  sourceId?: string;
  title?: string;
  dueAt?: string | null;
  timeZone?: string;
  state?: FollowUpState;
  evidence?: Record<string, unknown>;
  revision?: number;
}

export interface ContactPolicy {
  revision: number;
  liveDeliveryEnabled: boolean;
  /** The channels the policy lists (`call`, `email`, `push`, `in_app`); a list, as founder_contact sends it. */
  channels: string[];
  destinationRef: string | null;
  quietStart: number;
  quietEnd: number;
  timeZone: string;
  dailyCap: number;
  concurrentCap: number;
  eventAllowlist: string[];
  budgetUsdMicroDaily: number;
  updatedAt?: Timestamp | null;
}

export interface BriefingSchedule {
  id: string;
  kind: 'daily' | 'weekly';
  localTime: string;
  weekdays: number[];
  timeZone: string;
  enabled: boolean;
  nextAt: Timestamp | null;
  revision: number;
  createdAt: Timestamp;
}

export interface BriefingScheduleBody {
  kind: 'daily' | 'weekly';
  localTime: string;
  weekdays?: number[];
  timeZone: string;
  enabled?: boolean;
}

export interface UnknownUsage {
  rows: Record<string, unknown>[];
  total?: number;
  [key: string]: unknown;
}

/* ---------- Founder Rafii (POST /agent/turns) ---------- */

export interface FounderChartContext {
  chartId: string;
  viewVersion: number;
  queryReceiptId?: string | null;
  selection?: Record<string, string | number | boolean> | null;
}

/** What the page tells Rafii: opaque ids and plain view values, never records (CONTRACTS §6, PRD §6.2). */
export interface FounderPageContext {
  route: string;
  section: string;
  mode: FounderMode;
  environment: FounderEnvironment | null;
  selectedEntity?: { type: string; id: string } | null;
  chart?: FounderChartContext | null;
  period?: string | null;
  filters?: Record<string, string | number | boolean | string[]>;
  incidentId?: string | null;
  outline?: PageOutlineItem[];
  uiCapabilities: string[];
}

export interface FounderAgentTurnRequest {
  message: string;
  idempotencyKey: string;
  conversationId?: string | null;
  mode: FounderMode;
  modality: 'text';
  pageContext: FounderPageContext;
  timeZone?: string;
  locale?: string;
}

export interface FounderLink {
  type: string;
  id: string;
  href: string;
  label?: string | null;
}

/** The founder section of a turn result (CONTRACTS §4): facts cite receipts; totals are never computed by the model. */
export interface FounderAgentSection {
  receiptIds: string[];
  facts: string[];
  hypotheses: string[];
  recommendations: string[];
  unknowns: string[];
  links: FounderLink[];
}

export type FounderRunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'blocked' | string;

export interface FounderAgentTurnResponse {
  conversationId: string;
  runId: string | null;
  messageId: string | null;
  status: FounderRunStatus;
  result: AgentResult | null;
  founder?: FounderAgentSection | null;
  traceId?: string;
  blocker?: string | null;
}

export interface FounderAgentRun {
  runId: string;
  conversationId: string;
  status: FounderRunStatus;
  result: AgentResult | null;
  founder?: FounderAgentSection | null;
  messageId?: string | null;
}

export interface FounderConversationState {
  conversationId: string;
  mode: FounderMode;
  environment: FounderEnvironment;
  turns: number;
  lastRunId?: string | null;
  updatedAt?: string | null;
  historicalContext?: boolean;
}
