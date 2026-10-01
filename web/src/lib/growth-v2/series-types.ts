/**
 * Signature Series API shapes (server: src/postriff_phase2/series/views.py, http.py). Everything here is read back from
 * the server after each change; the browser never derives a series state on its own.
 */
export type SeriesRole = 'explanation' | 'worked_example' | 'case_study' | 'faq' | 'update';
export type SeriesStatus = 'active' | 'paused' | 'completed' | 'archived';
export type EpisodeWorkflowState = 'planned' | 'approved' | 'drafting' | 'drafted' | 'skipped';
/** `published` is derived from Queue: a linked draft was verified as published. */
export type EpisodeState = EpisodeWorkflowState | 'published';
export type FreshnessState = 'ok' | 'removed' | 'expired' | 'source_changed' | 'source_unavailable' | 'missing_support';
export type FactReason = 'claim_expired' | 'source_unavailable' | 'missing_support' | 'source_changed';
export type DecisionKind = 'accept' | 'reject' | 'do_not_repeat';
export type DecisionLevel = 'angle' | 'role';
export type NextActionKind = 'review_facts' | 'resume' | 'none' | 'add_draft' | 'approve_next' | 'plan_more';
export type EpisodeBlock = 'needs_fact_review' | 'episode_pending' | 'series_inactive' | null;

export interface SeriesClaim {
  id: string;
  text: string;
  claimType: 'quote' | 'statistic' | 'event' | 'statement' | string;
  reviewBy: string;
  status: 'supported' | 'removed';
  freshness: { state: FreshnessState; reason: FactReason | null; detail: string | null };
  support: { kind: 'post' | 'source' | 'user'; id: string | null; factId?: string | null; title: string | null; available: boolean };
}

export interface SimilarityWarning {
  id: string;
  code: 'similar_to_original' | 'similar_to_episode' | 'similar_to_post' | string;
  similarity: number;
  refId: string;
  index?: number;
}

export interface SeriesDraft {
  variantId: string;
  missing: boolean;
  platform: string | null;
  language: string | null;
  revision?: number;
  changedSinceLinked?: boolean;
  needsReview?: boolean;
  unknowns?: number;
  /** Queue holds this draft until the series' facts are reviewed. */
  factGate?: boolean;
  blocked?: boolean;
  published?: boolean;
  publishedJobId?: string | null;
  queued?: string | null;
  excerpt?: string;
  warnings: SimilarityWarning[];
}

export interface SeriesEpisode {
  id: string;
  index: number;
  role: SeriesRole;
  question: string;
  angle: { key: string; text: string };
  state: EpisodeState;
  workflowState: EpisodeWorkflowState;
  angleDecision: 'accepted' | 'rejected' | 'do_not_repeat' | null;
  factState: 'ok' | 'needs_fact_review';
  factReasons: FactReason[];
  claimIds: string[];
  drafts: SeriesDraft[];
  candidateDrafts: { variantId: string; platform: string | null; language: string | null; excerpt: string }[];
  assetIds: string[];
  lineage: { originKind: 'post' | 'source'; originId: string; originDigest: string } | null;
  basis: { reason: 'default' | 'accepted_role' | 'after_rejection'; decisionIds: string[] } | null;
  automation: { taskId: string; occurrenceId: string; at: number }[];
  covered: boolean;
  published: boolean;
  canApprove: boolean;
  blockedReason: EpisodeBlock;
  approvedAt?: number | null;
}

export interface SeriesDecision {
  id: string;
  decision: DecisionKind;
  level: DecisionLevel;
  role: SeriesRole;
  angleText: string | null;
  episodeId: string | null;
  /** `overlay`: kept in workspace memory (owner, memory on); `series`: kept on this series with the reason. */
  storage: 'overlay' | 'series';
  reason: 'overlays_disabled' | 'owner_required' | null;
  status: 'active' | 'revoked' | 'inactive';
  createdAt: number;
  revokedAt?: number | null;
  canRevoke: boolean;
}

export interface SeriesNextAction {
  kind: NextActionKind;
  episodeId?: string;
}

export interface SeriesView {
  id: string;
  revision: number;
  title: string;
  audienceQuestion: string;
  goal: string;
  language: string;
  owner: string;
  status: SeriesStatus;
  createdAt: number;
  updatedAt: number;
  origin: { kind: 'post' | 'source'; id: string; available: boolean; platform: string | null; publishedAt: string | null; title: string | null; excerpt: string };
  sources: { sourceId: string; title: string | null; available: boolean; versionCurrent: boolean }[];
  claims: SeriesClaim[];
  episodes: SeriesEpisode[];
  coverage: {
    audienceQuestion: string;
    covered: boolean;
    questions: { episodeId: string; index: number; role: SeriesRole; question: string; state: EpisodeState; covered: boolean }[];
    coveredCount: number;
    publishedCount: number;
    total: number;
  };
  decisions: SeriesDecision[];
  followers: { taskId: string; name: string | null; status: string | null }[];
  injectionFlags: number;
  nextAction: SeriesNextAction;
  limits: { maxPlan: number; maxEpisodes: number; maxDrafts: number; reviewMaxDays: number };
  definitionVersion: string;
  asOf: number;
  dataState: 'available' | 'partial' | 'unavailable' | 'stale';
}

export interface SeriesSummary {
  id: string;
  revision: number;
  title: string;
  audienceQuestion: string;
  status: SeriesStatus;
  language: string;
  createdAt: number;
  updatedAt: number;
  nextAction: SeriesNextAction;
  origin: { kind: 'post' | 'source'; available: boolean; platform: string | null; publishedAt: string | null; title: string | null };
  episodes: number;
  coveredCount: number;
  publishedCount: number;
  needsFactReview: number;
  followers: number;
}

export interface SeriesPage {
  items: SeriesSummary[];
  nextCursor: string | null;
  limit: number;
  canEdit: boolean;
  definitionVersion: string;
  asOf: number;
  dataState: string;
}

export interface SeriesDetail {
  series: SeriesView;
  canEdit: boolean;
  isOwner: boolean;
}

export interface SeriesMutation extends SeriesDetail {
  result: Record<string, unknown> | null;
  replayed: boolean;
  /** The server re-read the series and found this change saved. */
  verified: boolean;
}

export interface CandidatePost {
  kind: 'post';
  id: string;
  platform: string | null;
  language: string | null;
  publishedAt: string;
  excerpt: string;
  priorUse: { kind: 'automation' | 'series'; id: string }[];
  /** Only against at least three comparable posts; an observation, never a cause. */
  observed: { metric: string; value: number; typical: number; sampleSize: number; causal: false } | null;
}

export interface CandidateSource {
  kind: 'source';
  id: string;
  title: string;
  approvedFacts: number;
  excerpt: string;
  createdAt: number;
}

export interface CandidatesPage<T> {
  items: T[];
  nextCursor: string | null;
  limit: number;
  minAgeDays?: number;
  observedState?: 'available' | 'unavailable';
  dataState: string;
  asOf: number;
}

export interface DraftCheck {
  variantId: string;
  episodeId: string;
  refusal: { code: string; message: string; duplicateOf?: { kind: 'original' | 'post' | 'episode'; id: string } } | null;
  warnings: SimilarityWarning[];
}

export interface CreateSeriesInput {
  origin: { kind: 'post' | 'source'; id: string };
  audienceQuestion: string;
  goal: string;
  title?: string;
  episodeCount?: number;
  minAgeDays?: number;
  sourceIds?: string[];
  language?: string;
}

export type ClaimAction = { action: 'reviewed'; reviewBy: string } | { action: 'update'; text: string; reviewBy: string; support?: { sourceId: string; factId?: string } } | { action: 'remove' };
