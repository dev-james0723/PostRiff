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
  /** statement: an AI sentence verified against quotations; quotation: verbatim text; conflict: sources disagree. */
  kind?: 'statement' | 'quotation' | 'conflict';
  sourceRefs: (SourceRef & { locatorLabel?: string; displayTitle?: string; excerpt?: string })[];
}

export interface AnswerResult {
  contractVersion: string;
  /** Composed only from verified claims (or the abstention notice). */
  answer: string;
  claims: AnswerClaim[];
  coverage: SearchCoverage;
  warnings: string[];
  abstained?: boolean;
  /** llm: verified AI statements; extractive: verbatim quotations (no LLM grant or provider); none: abstained. */
  mode?: 'llm' | 'extractive' | 'none';
  scope?: string;
  /** What the scope holds for browsing (to disclose what answers could not use). */
  scopeCoverage?: SearchCoverage;
  attributionOnly?: boolean;
  approvedFacts?: boolean;
  provider?: Record<string, unknown> | null;
  droppedClaims?: number;
  promptVersion?: string | null;
}

/** POST …/viewer: an authorized target minted per request (signed links last at most 300 s; re-request on expiry). */
export interface ViewerTarget {
  kind: 'signedUrl' | 'proxy';
  url?: string;
  href?: string;
  expiresIn: number | null;
  expiresAt?: number;
  refresh: boolean;
  mime?: string | null;
}

export interface ViewerResult {
  assetRef: AssetRef;
  versionNo: number;
  /** An old citation opens its OLD version; the newest one is reported here, never substituted. */
  isCurrentVersion: boolean;
  currentAssetRef: AssetRef;
  displayTitle?: string | null;
  kind?: string | null;
  mime?: string | null;
  locator: Locator | null;
  locatorLabel: string | null;
  passage: { segmentId: string; text: string; kind: string; language: string | null; superseded: boolean } | null;
  target: ViewerTarget;
}

/* --- Smart Collections (collections.py, rule_schema 1) -------------------------------------------------------------- */

export type SmartRuleField =
  | 'kind' | 'tag' | 'title_contains' | 'filename_contains' | 'created_after' | 'created_before' | 'mime_prefix' | 'language'
  | 'capability' | 'source_kind' | 'duration_ms' | 'orientation' | 'usage' | 'text_matches';

export interface SmartRulePredicate {
  field: SmartRuleField;
  op: string;
  value: unknown;
  origin?: 'user' | 'ai_suggested' | 'any';
  timeZone?: string;
  capability?: LibraryCapability;
}

export type SmartRule = { all: SmartRule[] } | { any: SmartRule[] } | { not: SmartRule } | SmartRulePredicate;

export interface CollectionMember {
  assetRef: AssetRef;
  origin: 'rule' | 'include' | 'manual';
  title: string;
  kind: string;
  provenance: unknown[];
}

export interface CollectionPreview {
  rule: SmartRule;
  ruleSchema: number;
  /** Plain-language explanation generated by the server from the normalized rule. */
  explanation: string;
  count: number;
  counts: { rule: number; include: number };
  members: CollectionMember[];
  page: { offset: number; limit: number; nextOffset: number | null };
  coverage: { evaluated: number; partial: boolean; notYetProcessed: number };
  unavailableIncludes: number;
  /** Against the saved collection (null for a new one). Removed samples are asset keys. */
  changes: { added: { count: number; sample: AssetRef[] }; removed: { count: number; sample: string[] } } | null;
  warnings: string[];
}

export interface CollectionDefinition {
  id: string;
  name: string;
  kind: 'manual' | 'smart';
  rule: SmartRule | null;
  ruleSchema: number | null;
  explanation: string | null;
  revision: number;
  lastEvaluatedRevision: number | null;
  /** False while membership is being re-evaluated for the newest criteria. */
  evaluationCurrent: boolean;
  memberCount: number;
  members: Record<string, number>;
  overrides: { include: number; exclude: number };
  createdAt: number | null;
  updatedAt: number | null;
}

export interface CollectionHistoryEntry {
  revision: number;
  action: string | null;
  explanation: string | null;
  memberCount: number | null;
  byYou: boolean;
  createdAt: number | null;
  restoredRevision?: number;
}

export interface CollectionDetail {
  collection: CollectionDefinition;
  history: CollectionHistoryEntry[];
  canUndo: boolean;
}

export interface CollectionWriteResult {
  collection: CollectionDefinition;
  organizationRevision: number;
  warnings: string[];
  changes?: { added: number; removed: number };
}

/* --- versions, relations and comparison (relations.py, comparison.py) ----------------------------------------------- */

export interface RelatedOther {
  kind: string;
  available?: boolean;
  assetRef?: AssetRef;
  title?: string;
  assetKind?: string;
  versionNo?: number;
  key?: string;
}

export interface RelationEntry {
  id: string;
  relation: 'derived_from' | 'version_of' | 'supersedes' | 'used_in' | 'similar_to';
  status: string;
  origin: string;
  direction: 'out' | 'in';
  other: RelatedOther;
  evidence: Record<string, unknown>;
  createdAt: number | null;
  segmentId?: string;
}

export interface LineageWalk {
  nodes: { key: string; depth: number; assetRef?: AssetRef; title?: string; versionNo?: number; available?: boolean }[];
  truncated: boolean;
}

export interface RelatedResult {
  assetRef: AssetRef;
  versions: { assetRef: AssetRef; versionNo: number; title: string; createdAt: number; current: boolean }[];
  relations: RelationEntry[];
  lineage: { ancestors: LineageWalk; descendants: LineageWalk };
  /** Suggestions only: never merged, hidden or deleted. */
  nearDuplicates: { available: boolean; suggestions: RelationEntry[]; note: string };
  exactDuplicates: { count: number; note: string };
  truncated: boolean;
}

export interface VersionApproval {
  status: string;
  label: string;
  approvedFacts: number;
  useApproved: boolean;
  draftEvidence: { allowed: boolean; reason: string | null };
  publicUse: { allowed: boolean; reason: string | null };
}

export interface VersionStackEntry {
  assetRef: AssetRef;
  versionNo: number;
  title: string;
  filename: string | null;
  createdAt: number;
  status: string;
  current: boolean;
  approval: VersionApproval;
}

export interface AffectedDependent {
  kind: 'draft' | 'post' | 'source_pack' | 'idea';
  key: string;
  label: string;
  citesVersion: AssetRef;
  currentVersion: AssetRef;
  status: string;
  /** False for sources imported from an older version after it was superseded (not yet flagged). */
  flagged: boolean;
}

export interface VersionStack {
  assetRef: AssetRef;
  current: AssetRef;
  versions: VersionStackEntry[];
  affected: AffectedDependent[];
  truncated: boolean;
}

export interface ComparisonSide {
  assetRef: AssetRef;
  versionNo: number;
  title: string;
  filename: string | null;
  kind: string;
  mime: string;
  bytes: number | null;
  createdAt: number;
  approval: VersionApproval;
  usage: { count: number; events: { type: string; draftId: string | null; postId: string | null; channel: string | null; metrics: 'recorded' | 'unknown' }[]; usedIn: { kind: string; key: string; status: string }[] };
}

export interface DiffLine {
  text: string;
  segmentId?: string;
  locator?: Locator | null;
}

export type DiffHunk = { op: 'equal'; count: number } | { op: 'replace' | 'delete' | 'insert'; left: DiffLine[]; right: DiffLine[]; clipped?: boolean };

export interface ComparisonResult {
  contractVersion: string;
  mode: 'text' | 'image' | 'media' | 'unsupported';
  supported: boolean;
  left: ComparisonSide;
  right: ComparisonSide;
  metadata: { field: string; left: unknown; right: unknown; changed: boolean }[];
  relationship: { sameAsset: boolean; newer: 'left' | 'right' | null };
  warnings: string[];
  message?: string;
  text?: {
    left: { source: string; lines: number };
    right: { source: string; lines: number };
    summary: { added: number; removed: number; changed: number; unchanged: number };
    hunks: DiffHunk[];
    truncated: boolean;
    available: boolean;
  };
  image?: {
    left: { assetRef: AssetRef; width: number | null; height: number | null; orientation: string | null };
    right: { assetRef: AssetRef; width: number | null; height: number | null; orientation: string | null };
    sameDimensions: boolean | null;
    note: string;
  };
  media?: {
    left: { assetRef: AssetRef; durationMs: number | null; segments: { segmentId: string; kind: string; locator: Locator; text: string }[] };
    right: { assetRef: AssetRef; durationMs: number | null; segments: { segmentId: string; kind: string; locator: Locator; text: string }[] };
    durationDeltaMs: number | null;
  };
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
  /** Required by source packs: a pack never defaults to the whole Library. */
  scope?: LibraryScope;
  purpose?: LibraryPurpose;
}

/** Library state carried to a draft and back (`source_packs.return_to`): bounded, link-free, never identity. */
export interface LibraryReturnTo {
  query?: string;
  scope?: LibraryScope;
  filters?: LibraryFilters;
  sort?: string;
  density?: string;
  /** 32-hex asset keys. */
  selection?: string[];
  anchor?: string;
  view?: string;
}

/** approved_public | needs_review | internal | unknown: a constraint to check, never "cleared". */
export type PackRights = 'approved_public' | 'needs_review' | 'internal' | 'unknown';

export interface PackEvidenceRef {
  purpose: 'evidence';
  selection: 'user' | 'recommended';
  assetRef: AssetRef;
  title: string;
  kind: string;
  locatorLabel: string;
  review: 'approved' | 'needs_review';
  reviewReason: string | null;
  rights: PackRights | string;
  current: boolean;
  why: string[];
  segmentId?: string;
  locator?: Locator;
}

export interface PackStyleRef {
  purpose: 'style';
  polarity: 'positive' | 'negative';
  sampleId: string;
  voiceSourceId: string | null;
  assetRef: AssetRef;
  locator?: Locator | null;
  locatorLabel?: string | null;
  language?: string | null;
}

/** A gap, a rights/currency note or a rationale line. `assetRef` names the ref it is about, when it is about one. */
export interface PackNote {
  code: string;
  message: string;
  assetRef?: AssetRef;
}

/** What narrowed since the pack's snapshot (`source_packs._revalidate`). */
export interface PackChange {
  purpose: 'evidence' | 'style' | 'pack';
  assetRef: Partial<AssetRef>;
  change: string;
  before?: { allowed?: boolean };
  after?: { allowed?: boolean; reason?: string | null; message?: string | null };
  message?: string;
}

/** The fields the existing writer takes (`ideas.turn`): Ideas source ids, voice mode and voice samples. */
export interface PackComposer {
  draftId: string;
  sourcePackId: string;
  sourceIds: string[];
  voiceMode: 'personalized' | 'neutral';
  voiceSourceIds: string[];
}

export interface SourcePack {
  contractVersion?: string;
  packId: string;
  revision: number;
  status: 'draft' | 'attached' | 'superseded' | 'revoked';
  taskContext: TaskContext;
  returnTo: LibraryReturnTo | null;
  evidenceRefs: PackEvidenceRef[];
  styleRefs: PackStyleRef[];
  rationale: PackNote[];
  gaps: PackNote[];
  rightsWarnings: PackNote[];
  grantRevision: number;
  draftId: string | null;
  style: { personaId: string; language: string | null } | null;
  limits: { maxEvidence: number; maxRecommended: number };
  warnings?: string[];
  /** GET only: selected items that became inaccessible were dropped from returnTo (counted, never named). */
  returnToRemoved?: number;
  validity?: { attachable: boolean; changes: PackChange[] };
}

export type PackAttachResult =
  | {
      status: 'applied';
      alreadyAttached: boolean;
      packId: string;
      revision: number;
      draftId: string;
      composer: PackComposer | null;
      returnTo: LibraryReturnTo | null;
      gaps: PackNote[];
      rightsWarnings: PackNote[];
      warnings: string[];
    }
  | {
      status: 'conflict';
      packId: string;
      revision: number;
      packStatus: SourcePack['status'];
      draftId: string;
      changes: PackChange[];
      grantRevision: { snapshot: number; current: number };
    };

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

export type SuggestionCategory = 'outdated_source' | 'unused_relevant' | 'missing_input' | 'failed_processing' | 'organization' | 'permission' | 'source_integrity';
export type SuggestionAction = 'open' | 'dismiss' | 'snooze' | 'apply' | 'disable_category';

/** suggestions.py `_public`: what was found, what it affects, and the actions this item allows. */
export interface LibrarySuggestion {
  id: string;
  category: SuggestionCategory;
  /** Permission and source-integrity warnings: never capped, never switched off. */
  critical: boolean;
  reason: string;
  /** Affected work: {kind, key} for drafts, packs, posts, ideas and items; {kind: 'proposal', name, itemCount} for organization proposals. */
  affected: { kind: string; key?: string; name?: string; itemCount?: number; citesVersion?: AssetRef; recipient?: string }[];
  candidateRefs: AssetRef[];
  why: Record<string, unknown> | null;
  state: 'new' | 'seen' | 'dismissed' | 'snoozed' | 'applied' | 'expired' | 'suppressed';
  snoozeUntil: number | null;
  createdAt: number | null;
  expiresAt: number | null;
  actions: SuggestionAction[];
  proposal?: { name: string; rule: SmartRule };
}

export interface SuggestionInbox {
  suggestions: LibrarySuggestion[];
  cap: { noncriticalPerDay: number; shownToday: number };
  preferences: Record<SuggestionCategory, { disabled: boolean; snoozeDays: number; canDisable: boolean }>;
  /** In-app only: channels ['in_app'], external false, with the server's own note. */
  delivery: { channels: string[]; external: boolean; note: string };
  proactiveEnabled: boolean;
}

/** usage.py `_metric`: a reading with its source time. A missing value is null and displays "unknown", never 0. */
export interface MetricReading {
  value: number | null;
  display: string;
  availability: string;
  observedAt: number | null;
  readOffset?: unknown;
}

/** usage.py `asset_usage` entries: library events, prepared posts, Ideas drafts and citations of this item's versions. */
export interface UsageEntry {
  source: 'library_event' | 'post_job' | 'post_review' | 'ideas_draft' | 'citation';
  type: string;
  version: AssetRef | null;
  at?: number | null;
  draftId?: string | null;
  postId?: string | null;
  jobId?: string | null;
  reviewId?: string | null;
  sourceId?: string | null;
  channel?: string | null;
  account?: string | null;
  state?: string | null;
  kind?: string;
  key?: string;
  status?: string;
  segmentId?: string;
  metrics?: Record<string, MetricReading> | null;
  metricsStatus: 'available' | 'partial' | 'unknown' | 'not_applicable';
}

export interface AssetUsage {
  assetRef: AssetRef;
  versions: AssetRef[];
  uses: UsageEntry[];
  summary: { uses: number; drafts: number; posts: number; channels: string[]; metricsStatus: string };
  /** The server's own words: correlation, not causation; missing values stay unknown. */
  note: string;
  truncated: boolean;
  warnings: string[];
}

/** voice.py `sample_contract`: one approved (or withdrawn) span with its provenance. No score. */
export interface VoiceSample {
  contractVersion: string;
  sampleId: string;
  voiceSourceId: string | null;
  assetRef: AssetRef;
  locator: Locator;
  locatorLabel: string;
  text: string | null;
  textHash: string;
  personaId: string;
  brand: string | null;
  language: string;
  polarity: 'positive' | 'negative';
  status: 'approved' | 'revoked' | 'blocked';
  statusReason: string | null;
  revision: number;
  consentRevision: number;
  attestation: { authoredByMe?: boolean; method?: string; speakerLabel?: string; generatedTextApproved?: boolean };
  uses: { purpose: string; route: string }[];
  selected: boolean;
  createdAt: number | null;
  revokedAt: number | null;
}

export interface AssetVoice {
  contractVersion: string;
  assetRef: AssetRef;
  samples: VoiceSample[];
  negatives: VoiceSample[];
  voicePermission: { allowed: boolean; reason: string | null; message: string | null; grantRevision: number };
  sourceRole: { role: 'generated' | 'reference' | 'own_note' | 'unattested'; detail: string };
  admission: { enabled: boolean; canApprove: boolean; methods: ('written_by_me' | 'spoken_by_me' | 'published_by_me')[] };
  explanation: string;
}

export interface LibraryIntelligenceStatus {
  flags: Record<string, boolean>;
  providers: Record<string, { available: boolean; reason: string | null; model: string }>;
  revisions: { grantRevision: number; indexGeneration: number; organizationRevision: number };
}
