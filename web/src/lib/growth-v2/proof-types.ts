/** Wire types for `/api/workspaces/{id}/proof` (src/postriff_phase2/proof): versioned Growth Loop proofs and next-week decisions. */

export type ProofDataState = 'available' | 'partial' | 'unavailable' | 'restricted';
export type FigureName = 'acceptedWork' | 'verifiedPublications' | 'assistedExports' | 'unresolvedSlots' | 'outcomes' | 'timeBack' | 'providerCost';

export interface ProofFigure {
  value: unknown;
  dataState: ProofDataState;
  definition: string;
  evidence: Record<string, string[]>;
  evidenceTruncated: boolean;
  reason?: string;
  byReason?: Record<string, number>;
  approved?: number;
  visibility?: 'owner';
  /** When a sibling feature reports counts without ids, the scoped records the figure counts (resource + period). */
  evidenceQuery?: { resource: string; from: number; to: number };
}

export interface TimeBackClass {
  confidence: 'estimated' | 'personalized' | 'measured';
  outcomes: number;
  savedSeconds: number;
}

export interface ProviderCost {
  actualUsdMicro: number;
  actualEntries: number;
  unknownEntries: number;
  unknownReservedEstimateUsdMicro: number;
}

export interface ProofCounts {
  definitionVersion: string;
  frequency: 'weekly' | 'monthly';
  period: { start: number; end: number; timeZone: string; timeZoneSource: string; label: string };
  asOf: number;
  sourceWatermark: Record<string, number | null>;
  maturity: { mature: boolean; maturesAt: number };
  dataState: ProofDataState;
  figures: Record<FigureName, ProofFigure>;
  coverage: { figure: FigureName; dataState: ProofDataState; reason: string | null }[];
  limitations: string[];
}

export interface CorrectionEntry {
  figure: string;
  before: unknown;
  after: unknown;
  dataStateBefore?: string;
  dataStateAfter?: string;
  evidenceOnly?: boolean;
  /** Cost corrections are owners-only: other members see that the figure changed, not the amounts. */
  restricted?: boolean;
}

export interface ProofRevisionSummary {
  id: string;
  revision: number;
  asOf: number;
  dataState: ProofDataState;
  reason: 'initial' | 'late_data' | 'definition_change';
  correction: CorrectionEntry[];
  createdAt: number;
  definitionVersion: string;
}

export type DecisionStatus = 'proposed' | 'accepted' | 'edited' | 'rejected' | 'revoked';
export type DecisionAction = 'accept' | 'edit' | 'reject' | 'revoke';

export interface DecisionScope {
  goalId: string | null;
  channelId: string | null;
  language: string | null;
  contentType: string | null;
}

export interface StrategyDecision {
  id: string;
  revision: number;
  status: DecisionStatus;
  kind: 'experiment_preference' | 'brief_topic';
  statement: string;
  scope: DecisionScope;
  appliesFrom: number | null;
  /** The local Monday (YYYY-MM-DD, workspace zone) the decision first applies to; shown as a date, never re-zoned. */
  appliesFromDate?: string | null;
  createdAt: number;
  basis: Record<string, string>;
  inEffect: boolean;
  actions: DecisionAction[];
  versions?: { revision: number; status: DecisionStatus; decidedBy: string | null; at: number }[];
}

export interface ProofView {
  proofId: string;
  frequency: 'weekly' | 'monthly';
  periodStart: number;
  periodEnd: number;
  timeZone: string;
  timeZoneSource: string;
  legacyRecap: boolean;
  maturity: { mature: boolean; maturesAt: number };
  href: string;
  latest: { id: string; revision: number; definitionVersion: string; asOf: number; sourceWatermark: Record<string, number | null>; dataState: ProofDataState;
            reason: ProofRevisionSummary['reason']; correction: CorrectionEntry[]; createdAt: number; counts: ProofCounts };
  revisions: ProofRevisionSummary[];
  nextStep: { proposals: StrategyDecision[]; rule: string };
}

export interface ProofList {
  proofs: ProofView[];
  definitionVersion: string;
  asOf: number;
  nextCursor: string | null;
}

export interface RefreshResult {
  proof: ProofView | null;
  appended: boolean;
  revision?: number;
  dataState?: 'unavailable';
  reason?: string;
  period?: { start: number; end: number; timeZone: string };
  verified: boolean;
}

export interface StrategyList {
  decisions: StrategyDecision[];
  inEffect: { id: string; revision: number; kind: string; statement: string; scope: DecisionScope; appliesFromDate: string | null }[];
  canDecide: boolean;
  nextCursor: string | null;
}

export interface DecideInput {
  action: DecisionAction;
  expectedRevision: number;
  idempotencyKey: string;
  statement?: string;
  scope?: Partial<DecisionScope>;
}

export interface DecideResult {
  decision: StrategyDecision;
  replayed: boolean;
  verified: boolean;
  /** `appliesFromDate`: the first local Monday whose weekly plan was not yet stored; `alreadyPlanned`: the weeks
   *  (YYYY-MM-DD) that were already planned when the decision was made and so do not use it. */
  planning?: { inEffect: boolean; appliesFromDate: string | null; alreadyPlanned?: string[]; note: string };
}

/** What a Weekly plan records about decisions (week.appliedDecisions / week.notApplied). */
export interface AppliedDecision {
  id: string;
  revision: number;
  kind?: string;
  slotIds: string[];
}

export interface NotAppliedDecision {
  id: string;
  revision: number;
  reason: 'applies_from_later' | 'already_applied' | 'source_unavailable' | 'account_unavailable' | 'goal_not_active' | 'no_matching_slot' | string;
}
