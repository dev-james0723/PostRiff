/**
 * Customer business results (RAFII Product Growth G2-OUT, PRD R-OUT-01..03). Mirrors `src/postriff_phase2/results`.
 * Three provenance classes never blend; money stays per currency in minor units; `null` means unavailable, not zero.
 */

export type ResultProvenance = 'provider_native' | 'first_party_reported' | 'user_declared';
export type ResultType = 'click' | 'lead' | 'booking' | 'newsletter_signup' | 'sale';
export type DeclarableResultType = Exclude<ResultType, 'click'>;
export type ResultAttribution = 'associated' | 'unattributed' | 'expired_window' | 'not_this_workspace';
export type ResultsDataState = 'available' | 'partial' | 'unavailable' | 'stale';
export type ResultProducer = 'form' | 'booking' | 'newsletter' | 'store' | 'other';
export type ConnectionAction = 'rotate' | 'pause' | 'resume' | 'remove';
export type LinkAction = 'disable' | 'enable';

export interface ResultMoney {
  /** Whole minor units (cents). */
  minor: number;
  /** Lower-case ISO 4217 code. */
  currency: string;
}

export interface ResultClassSummary {
  counts: Partial<Record<ResultType, number>>;
  /** One entry per currency; currencies are never added together. */
  money: Record<string, { minor: number; events: number }>;
  reversed: number;
  unattributed: number;
  associated: number;
}

export interface ResultsSummary {
  definitionVersion: string;
  definition: string;
  asOf: number;
  period: { start: number; end: number; open: boolean };
  dataState: ResultsDataState;
  /** `null` for a class means no data for it in this period (unavailable), never zero. */
  classes: Record<ResultProvenance, ResultClassSummary | null>;
  testEvents: number;
  quarantined: number;
  clicks: { counted: number; likelyBot: number; links: number; unit: 'clicks_not_people'; days: { start: string; end: string } } | null;
  coverage: {
    connections: { active: number; paused: number; removed: number; errored: number };
    lastReceivedAt: number | null;
    declarations: boolean;
    providerNative: 'not_connected';
  };
}

export interface ResultItem {
  id: string;
  provenance: ResultProvenance;
  type: ResultType;
  occurredAt: number;
  receivedAt: number;
  /** Received minus occurred, for connected-tool events. */
  lagSeconds: number | null;
  amount: ResultMoney | null;
  quantity: number;
  linkId: string | null;
  link: { label: string; slug: string } | null;
  campaignRef: string | null;
  attribution: ResultAttribution;
  attributionDefinition: string;
  /** The person's own note (declarations only). */
  note: string | null;
  connectionId: string | null;
  connection: { label: string; producer: ResultProducer } | null;
  test: boolean;
  revision: number;
  amended: boolean;
  status: 'active' | 'reversed';
  reversedAt: number | null;
  reversalId: string | null;
  /** True for the person's own, not reversed declarations. */
  editable: boolean;
}

export interface ResultsPage {
  items: ResultItem[];
  nextCursor: string | null;
  limit: number;
  asOf: number;
  definition: string;
  canEdit: boolean;
}

export interface ResultFilters {
  provenance?: ResultProvenance;
  type?: ResultType;
  attribution?: ResultAttribution | 'not_associated';
  status?: 'active' | 'reversed';
}

export interface ResultDeclaration {
  type: DeclarableResultType;
  /** ISO-8601 with an offset. */
  occurredAt: string;
  amount?: ResultMoney | null;
  quantity?: number;
  note?: string | null;
  linkId?: string | null;
  campaignRef?: string | null;
}

export interface ResultMutation {
  result: ResultItem;
  replayed: boolean;
}

export interface ConnectionHealth {
  lastReceivedAt: number | null;
  lastEventAt: number | null;
  lagSeconds: number | null;
  lastErrorCode: string | null;
  lastErrorAt: number | null;
  dataState: ResultsDataState;
  reason: string | null;
  accepted24h: number;
  reversals24h: number;
  testEvents24h: number;
  quarantined: number;
  quarantined24h: number;
}

export interface ResultConnection {
  id: string;
  label: string;
  producer: ResultProducer;
  status: 'active' | 'paused' | 'removed';
  revision: number;
  /** A short non-reversible label of the current secret; never the secret. */
  fingerprint: string | null;
  previousFingerprint: string | null;
  previousExpiresAt: number | null;
  ratePerMinute: number;
  ratePerDay: number;
  createdAt: number;
  updatedAt: number;
  removedAt: number | null;
  /** Owners only. */
  endpoint: { path: string; url: string | null; method: 'POST'; signatureHeader: string; scheme: string; replayWindowSeconds: number; maxBodyBytes: number } | null;
  health: ConnectionHealth;
}

export interface ResultConnections {
  connections: ResultConnection[];
  canManage: boolean;
  limit: number;
  asOf: number;
  rotationGraceSeconds: number;
}

/** `secret` is present exactly once: in the answer that created or rotated it. A replay answers `null`. */
export interface ConnectionSecret {
  connection: ResultConnection;
  secret: string | null;
  secretShown: boolean;
  replayed: boolean;
}

export interface TrackingLink {
  id: string;
  slug: string;
  path: string;
  url: string | null;
  destination: string;
  campaignRef: string | null;
  label: string;
  status: 'active' | 'disabled';
  windowDays: number;
  definitionVersion: string;
  createdAt: number;
  updatedAt: number;
  disabledAt: number | null;
  revision: number;
  /** Clicks, not people. `likelyBot` is counted apart where detectable. */
  clicks: { counted: number; likelyBot: number; days: number; unit: 'clicks_not_people' };
  associatedResults: Partial<Record<ResultProvenance, number>>;
}

export interface TrackingLinks {
  items: TrackingLink[];
  nextCursor: string | null;
  limit: number;
  canEdit: boolean;
  definition: string;
  windowDays: number;
}

export interface TrackingLinkInput {
  destination: string;
  campaignRef?: string | null;
  label?: string | null;
}
