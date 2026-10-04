/**
 * Payload shapes the domain pages render. The contract types live in `@/lib/founder/types` (web-shell, CONTRACTS
 * §6) and are re-exported here under the pages' names; the handful below that the shell does not model (the
 * workspace query, source health rows as the server writes them, audit rows) are kept local and read defensively.
 * Nothing here is computed: values are shown as the server sent them.
 */
import type {
  BriefingSchedule as SharedBriefingSchedule,
  BriefingScheduleBody,
  ContactPolicy as SharedContactPolicy,
  DataState,
  FounderIncident,
  MetricQueryBody,
  MetricQueryResult,
  MetricReceipt,
  MetricRow,
  Timestamp
} from '@/lib/founder/types';

export type { Coverage, DataState, Envelope, FounderMode, MetricInterval, MetricRow, SourceHealth, Timestamp, UnknownUsage } from '@/lib/founder/types';
export type { FounderSession as SessionData } from '@/lib/founder/types';

export type MetricQuery = MetricQueryBody;

/** `POST /metrics/query` answers with the receipt body itself, not the standard envelope (`http.py`). */
export type MetricResult = MetricQueryResult;

export type RecordRow = Record<string, unknown> & { id: string };

/** `POST /workspace/{mode}/query` (`workspace.py::query`). */
export interface RecordsData {
  mode: 'live' | 'demo';
  rows: RecordRow[];
  workspaces: RecordRow[];
  total: number;
  page: number;
  pageSize: number;
  statuses: string[];
  linkedRecords?: Record<string, RecordRow[]>;
  linkedRecordCoverage?: Record<string, { state: 'connected' | 'not_configured'; total: number | null; limit: number; truncated: boolean }>;
  revision?: number;
  scenario?: string;
  filters?: Record<string, string>;
}

export interface RecordsQueryInput {
  collection: string;
  search: string;
  status: string;
  page: number;
  recordId: string;
  /** Demo-only refinements; the Live query rejects anything beyond the five required keys. */
  plan?: string;
  billingCycle?: string;
  sort?: string;
  direction?: 'asc' | 'desc';
}

export interface IncidentEvent {
  id?: string;
  kind: string;
  at: Timestamp;
  body?: Record<string, unknown> | null;
}

/** The shell's incident plus the optional fields the Demo scenario payload carries. */
export type Incident = FounderIncident & { timeline?: IncidentEvent[]; receiptIds?: string[] };

/** The shell's policy plus what the server may add about why live delivery cannot be enabled. */
export type ContactPolicy = SharedContactPolicy & { liveDeliveryBlockers?: string[]; providerConfigured?: boolean };

export type BriefingSchedule = SharedBriefingSchedule;
export type BriefingScheduleInput = BriefingScheduleBody;

/** `GET /sources/health` rows as `investigations.effective_quality` writes them (snake_case) or the 054 view (camelCase). */
export interface SourceHealthRow {
  source_id?: string;
  sourceId?: string;
  state: string;
  watermark?: string | null;
  lastGoodAt?: string | null;
  checked_at?: string | null;
  reasonCode?: string | null;
  reason?: string | null;
  qualified?: boolean;
  coverage_complete?: boolean;
  provenance?: string;
  source_version?: string;
  [key: string]: unknown;
}

/** `GET /audit` rows (`store.audit_read`): content-free. */
export interface AuditEvent {
  id: string;
  request_id?: string;
  actor?: string;
  environment?: string;
  action: string;
  result: string;
  error_code?: string | null;
  occurred_at: string;
}

export interface UnknownUsageRow {
  id: string;
  workspaceId?: string | null;
  feature?: string | null;
  provider?: string | null;
  model?: string | null;
  kind?: string | null;
  quantity?: number | null;
  unit?: string | null;
  estimatedUsdMicro?: number | null;
  costState?: string | null;
  at?: string | null;
  [key: string]: unknown;
}

/** A stored receipt; the store writes camelCase, older rows read back snake_case, so both spellings are read. */
export type Receipt = MetricReceipt & {
  data_state?: DataState;
  dataState?: DataState;
  query_digest?: string;
  queryDigest?: string;
  source_watermarks?: Record<string, string>;
  sourceWatermarks?: Record<string, string>;
  row_count?: number;
  rowCount?: number;
  result_rows?: MetricRow[];
  rows?: MetricRow[];
  normalized_query?: Record<string, unknown>;
  normalizedQuery?: Record<string, unknown>;
  calculated_at?: string;
  calculatedAt?: string;
};

/** A server error the api wrapper surfaces; only the fixed copy and the code are ever shown. */
export interface ControlFailure {
  message?: string;
  code?: string;
  status?: number;
}
