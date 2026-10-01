/** Wire types for `/api/workspaces/{id}/briefs` (src/postriff_phase2/briefs). Stored-only: nothing here is live research. */

export type DataState = 'available' | 'partial' | 'unavailable';
export type BriefSource = 'trends' | 'listening' | 'radar';
export type BriefEffort = 'quick' | 'medium' | 'deep';
export type BriefActionKind = 'accept' | 'save_idea' | 'dismiss' | 'not_relevant' | 'restore';
export type BriefReasonAction = 'dismiss' | 'not_relevant';

export interface BriefEvidence {
  url: string | null;
  ref: string | null;
  label: string | null;
  publishedAt: number | null;
  retrievedAt: number | null;
}

export interface BriefCoverage {
  availability: string;
  representation?: string;
  completeness?: string;
  scope?: string;
  note?: string;
}

export interface BriefMatch {
  kind: 'material' | 'goal' | 'brand' | 'interest' | 'fit';
  label: string;
  via?: string;
}

export interface BriefOutcomeRef {
  type: string;
  id: string;
}

export interface BriefDecision {
  action: BriefActionKind;
  reasonCode: string | null;
  outcomeRefs: BriefOutcomeRef[];
  createdAt: number;
}

export interface BriefItem {
  id: string;
  source: BriefSource;
  sourceRef: string;
  sourceRevision: string;
  kind: 'signal' | 'question' | 'whitespace';
  title: string;
  excerpt: string | null;
  evidence: BriefEvidence[];
  gapEvidence: string[];
  publishedAt: number | null;
  retrievedAt: number | null;
  expiresAt: number | null;
  freshnessBasis: string | null;
  dataMode: 'stored';
  coverage: BriefCoverage;
  relevance: { reason: string; matches: BriefMatch[] };
  angle: { id: string | null; text: string };
  effort: BriefEffort;
  action: { kind: 'accept' | 'save_idea'; angleIds?: string[]; platforms?: string[]; requires?: string[] };
  platforms: string[];
  language: string | null;
  limitations: string[];
  decision: BriefDecision | null;
}

export interface SourceCoverage {
  source: BriefSource;
  state: 'available' | 'empty' | 'unavailable' | 'stale';
  reason: string | null;
  considered: number;
  selected: number;
}

/** An item the person already decided on (this week, or marked not relevant recently), with the stored edition it is in. */
export type BriefHandledItem = BriefItem & { editionId: string };

export interface BriefEdition {
  id: string | null;
  persisted: boolean;
  editionKey: string;
  revision: number | null;
  periodStart: number;
  periodEnd: number;
  timeZone: string;
  cadence: 'weekly' | 'daily';
  materialDigest: string;
  deliveredAt: number | null;
  items: BriefItem[];
  handled?: BriefHandledItem[];
}

export interface BriefCurrent {
  definitionVersion: string;
  asOf: number;
  dataMode: 'stored';
  dataState: DataState;
  coverage: SourceCoverage[];
  excluded: Record<string, number>;
  considered: number;
  edition: BriefEdition;
  canAct: boolean;
  limitations: string[];
  reasons: Record<BriefReasonAction, string[]>;
}

export interface BriefActionInput {
  action: BriefActionKind;
  idempotencyKey: string;
  editionId?: string | null;
  materialDigest?: string;
  reasonCode?: string;
  angleId?: string;
  channelId?: string;
  goal?: string;
}

export interface BriefActionResult {
  action: { id: string; itemId: string; action: BriefActionKind; reasonCode: string | null; outcomeRefs: BriefOutcomeRef[]; createdAt: number; effort: BriefEffort | null };
  edition: { id: string; revision: number; editionKey: string };
  outcome: { sourceId: string; href: string } | null;
  replayed: boolean;
  verified: boolean;
}

export interface BriefEditionSummary {
  id: string;
  editionKey: string;
  revision: number;
  cadence: string;
  periodStart: number;
  periodEnd: number;
  timeZone: string;
  dataState: DataState;
  deliveredAt: number | null;
  createdAt: number;
  materialDigest: string;
  items: number;
  sources: BriefSource[];
  actions: Partial<Record<BriefActionKind, number>>;
}

export interface BriefHistory {
  editions: BriefEditionSummary[];
  nextCursor: string | null;
}
