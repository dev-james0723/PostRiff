/* Library intelligence v1 contracts (rafii-library/1). Mirrors src/postriff_phase2/library_intelligence/contracts.py.
 * Ids are opaque 32-hex strings. Nothing here carries workspace or actor identity: the server derives both. */

export type LibraryPurpose = 'browse' | 'answer' | 'draft_evidence' | 'voice' | 'memory' | 'public_use';
export type ProcessingLocation = 'local' | 'cloud';
export type ProviderCategory = 'extract' | 'ocr' | 'asr' | 'vision' | 'embedding' | 'llm';
export type LibraryCapability = 'preview' | 'extract' | 'transcribe' | 'visual' | 'embed_text' | 'embed_visual' | 'understand';
export type CapabilityStateName =
  | 'not_requested' | 'queued' | 'processing' | 'ready' | 'partial' | 'unsupported' | 'failed' | 'cancelled' | 'blocked_permission' | 'blocked_budget';
export type SearchMode = 'lexical' | 'semantic' | 'visual';

export interface AssetRef { assetId: string; versionId: string; sha256: string }

export type Locator =
  | { kind: 'page'; page: number; section?: string; textStart?: number; textEnd?: number }
  | { kind: 'time'; startMs: number; endMs: number }
  | { kind: 'text'; start: number; end: number }
  | { kind: 'slide'; slide: number }
  | { kind: 'sheet'; sheetName: string; cellRange: string }
  | { kind: 'imageRegion'; frameTimeMs?: number; x: number; y: number; width: number; height: number };

export interface SourceRef { assetRef: AssetRef; segmentId?: string; locator?: Locator; quoteHash?: string }

export type LibraryScope =
  | { kind: 'workspace' }
  | { kind: 'collection'; collectionId: string }
  | { kind: 'selection'; assetRefs: AssetRef[] };

export interface LibraryFilters {
  kinds?: ('image' | 'video' | 'audio' | 'document' | 'file')[];
  tags?: string[];
  createdFrom?: string;
  createdTo?: string;
  timeZone?: string;
  rights?: 'approved_public' | 'needs_review' | 'internal' | 'unknown';
  usage?: 'used' | 'unused';
  orientation?: 'portrait' | 'landscape' | 'square';
  minDurationMs?: number;
  maxDurationMs?: number;
  collectionId?: string;
  languages?: string[];
  capability?: LibraryCapability;
  capabilityState?: CapabilityStateName;
}

export interface LibrarySearchRequest {
  query: string;
  scope?: LibraryScope;
  purpose?: LibraryPurpose;
  filters?: LibraryFilters;
  modes?: SearchMode[];
  similarTo?: AssetRef;
  cursor?: string;
  limit?: number;
}

export interface CapabilityState {
  capability: LibraryCapability;
  state: CapabilityStateName;
  errorCode?: string;
  detail?: string;
  retryable?: boolean;
  progress?: { done: number; total: number } | null;
  processorVersion?: string;
  updatedAt?: number;
}

export interface MatchReason { kind: 'exact' | 'title' | 'filename' | 'hash' | 'id' | 'dimensions' | 'phrase' | 'lexical' | 'semantic' | 'visual' | 'tag'; detail?: string }

export interface SearchHit {
  assetRef: AssetRef;
  segmentId?: string;
  locator?: Locator;
  locatorLabel?: string;
  displayTitle: string;
  kind: 'image' | 'video' | 'audio' | 'document' | 'file';
  mime: string;
  snippet: string;
  matchReasons: MatchReason[];
  capabilities: CapabilityState[];
  sourceStatus: { purpose: LibraryPurpose; allowed: boolean; reason?: string | null; attributionOnly?: boolean; candidateOnly?: boolean };
  createdAt: number;
  /** The Ideas source this asset was imported as, if any. */
  sourceId?: string | null;
  /** Every matching passage or moment in this version (the best one is also on segmentId/locator). */
  passages?: { segmentId?: string; locator?: Locator; locatorLabel?: string; kind?: string; language?: string | null; mode?: SearchMode }[];
}

export interface SearchCoverage {
  scopeDescription: string;
  accessibleAssetCount: number;
  indexedAssetCount: number;
  pendingAssetCount: number;
  failedAssetCount: number;
  modesApplied: SearchMode[];
  partial: boolean;
  indexGeneration: number;
}

export interface SearchResponse {
  contractVersion: string;
  queryId: string;
  hits: SearchHit[];
  nextCursor: string | null;
  coverage: SearchCoverage;
  facets?: { kinds: Record<string, number>; tags: Record<string, number> };
  /** Server-side hit count; relation 'gte' when a bounded ranking stage reached its limit. */
  totalHits?: { value: number; relation: 'eq' | 'gte' };
  /** Ranking configuration (order only, never a confidence score). */
  ranking?: {
    version: string; k: number; weights: Record<string, number>; exactFirst: boolean; orderOnly: boolean;
    candidateLimits: Record<string, number>; boundsReached: string[] | Record<string, boolean>;
    semanticModel: string | null; visualModel: string | null; normalizerVersion: number;
  };
  warnings: string[];
}

export interface AnswerClaim {
  text: string;
  support: 'supported' | 'conflicting' | 'insufficient';
  sourceRefs: (SourceRef & { locatorLabel?: string; displayTitle?: string })[];
}

export interface AnswerResult {
  contractVersion: string;
  answer: string;
  claims: AnswerClaim[];
  coverage: SearchCoverage;
  warnings: string[];
  abstained?: boolean;
}

export interface Annotation {
  id: string;
  field: string;
  value: unknown;
  origin: 'extracted' | 'ai_suggested' | 'user_confirmed';
  evidence: SourceRef[];
  confidence?: number | null;
  model?: string | null;
  updatedAt: number;
}

export interface ContentSegment {
  id: string;
  kind: 'text' | 'page' | 'slide' | 'sheet' | 'transcript' | 'ocr' | 'caption' | 'scene' | 'moment' | 'note' | 'metadata';
  text: string;
  language?: string | null;
  locator?: Locator | null;
  locatorLabel?: string;
  speakerLabel?: string | null;
  origin: 'extracted' | 'ocr' | 'transcript' | 'user' | 'ai_suggested';
  uncertainty?: string | null;
  extractor: string;
  extractorVersion: string;
  correctionOf?: string | null;
}

export interface UnderstandingCard {
  contractVersion: string;
  assetRef: AssetRef;
  displayTitle: string;
  originalFilename: string;
  kind: string;
  mime: string;
  summary: { text: string; origin: Annotation['origin'] } | null;
  topics: Annotation[];
  usefulSegments: ContentSegment[];
  suggestedUses: Annotation[];
  annotations: Annotation[];
  sourceStatus: Record<LibraryPurpose, { allowed: boolean; reason?: string | null }>;
  capabilityStates: CapabilityState[];
  media: { durationMs?: number; width?: number; height?: number; pages?: number; slides?: number; peaks?: number[]; peaksSource?: string };
  versions: { versionId: string; versionNo: number; createdAt: number; current: boolean }[];
}

export interface TaskContext {
  taskId?: string;
  draftId?: string;
  userGoal: string;
  audience?: string;
  channels?: string[];
  locale?: string;
  personaId?: string;
  selectedSourceRefs: SourceRef[];
  scope?: LibraryScope;
  purpose?: LibraryPurpose;
}

export interface SourcePack {
  packId: string;
  revision: number;
  taskContext: TaskContext;
  evidenceRefs: (SourceRef & { displayTitle: string; rationale: string; rights: string })[];
  styleRefs: (SourceRef & { displayTitle: string; rationale: string; sampleId: string })[];
  rationale: string[];
  gaps: { kind: string; message: string }[];
  rightsWarnings: { assetId: string; message: string }[];
  status: 'draft' | 'attached' | 'superseded' | 'revoked';
}

export type LibraryActionType =
  | 'collection.save' | 'collection.override' | 'collection.undo' | 'collection.preview' | 'sources.select' | 'source_pack.create'
  | 'source_pack.attach' | 'version.link' | 'version.accept_replacement' | 'annotation.correct' | 'suggestion.set_state'
  | 'moment.save' | 'voice.approve_span' | 'voice.revoke' | 'metadata.update';

export interface ActionEnvelope {
  actionId: string;
  uiInstanceId: string;
  actionType: LibraryActionType;
  targetRefs: AssetRef[];
  expectedRevision?: number | null;
  idempotencyKey: string;
  payload: Record<string, unknown>;
}

export interface ActionResult<T = unknown> {
  status: 'applied' | 'requires_confirmation' | 'conflict' | 'denied';
  revision?: number;
  result?: T;
  warnings: string[];
  replayed?: boolean;
}

export interface LibraryGrant {
  id: string;
  grantType: 'purpose' | 'processing';
  scopeKind: 'workspace' | 'asset' | 'collection';
  scopeKey: string;
  memberKeys: string[];
  purpose: LibraryPurpose | null;
  location: ProcessingLocation | null;
  category: ProviderCategory | null;
  grantedAt: number;
}

export interface LibrarySuggestion {
  id: string;
  category: 'outdated_source' | 'unused_relevant' | 'missing_input' | 'failed_processing' | 'organization' | 'permission' | 'source_integrity';
  critical: boolean;
  reason: string;
  candidateRefs: SourceRef[];
  affected: { kind: string; id: string; label: string }[];
  state: 'new' | 'seen' | 'dismissed' | 'snoozed' | 'applied' | 'expired' | 'suppressed';
  snoozeUntil: number | null;
  createdAt: number;
}

export interface UsageEntry {
  eventType: 'source_pack' | 'draft_attached' | 'post_scheduled' | 'post_published' | 'agent_answer' | 'downloaded';
  at: number;
  draftId?: string | null;
  postId?: string | null;
  channel?: string | null;
  versionId?: string | null;
  metrics: Record<string, number | null> | null;
  metricsAt: number | null;
}

export interface LibraryIntelligenceStatus {
  flags: Record<string, boolean>;
  providers: Record<string, { available: boolean; reason: string | null; model: string }>;
  revisions: { grantRevision: number; indexGeneration: number; organizationRevision: number };
}
