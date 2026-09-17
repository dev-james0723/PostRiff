/**
 * Typed contracts for the hosted PostRiff API (Python, served at /api/*).
 * Ported from the founder alpha client (`studio/web/src/founder/cloud-api.ts`)
 * and kept in one place so every page reads the same shapes.
 */
import type { WorkspaceRole } from '@/types';

export type AuthMode = 'supabase' | 'dev';

export interface Catalog {
  authMode: AuthMode;
  execution: string;
  phase2?: boolean;
  templates: unknown[];
  routes: { id: string; label: string; status: string; detail: string }[];
  profileMetadata: unknown;
}

export interface Membership {
  role: WorkspaceRole;
  can_publish: boolean;
  can_reply: boolean;
  can_moderate: boolean;
  can_manage_connections: boolean;
}

export interface WorkspaceListItem {
  workspaceId: string;
  membership: Membership;
  createdAt: number;
}

/* ---------- workspace snapshot (single mutation channel: POST /actions) ---------- */

export interface Asset {
  id: string;
  hash: string;
  mime: string;
  width?: number;
  height?: number;
  bytes?: number;
  deleted: boolean;
  storagePath?: string;
}

export interface Manifest {
  workspaceId: string;
  actor: string;
  account: string;
  platform: string;
  operation: string;
  variantId: string;
  contentRevision: number;
  payload: { text: string; language: string };
  media: (Asset & { alt: string })[];
  timing: { local: string; timeZone: string; utc: string };
  expiresAt: number;
  idempotencyKey: string;
  execution: string;
}

export interface Job {
  id: string;
  manifest: Manifest;
  state: string;
  events: { at: number; state: string; message: string }[];
  attempts: { number: number; startedAt: number; endedAt?: number }[];
  providerReference?: string;
  providerConfirmed?: string;
  nextAction?: string;
  cancelRequested: boolean;
  verification?: { method: string; at: number } | null;
}

export interface Review {
  id: string;
  manifest: Manifest;
  digest: string;
  status: string;
}

export interface Trial {
  plan: string;
  startedAt: number;
  expiresAt: number;
  writingGrant: number;
  writingUsed: number;
  artworkUsed: number;
  status: string;
}

export interface SnapshotVariant {
  id: string;
  platform: string;
  language: string;
  text: string;
  revision: number;
  voiceRevision: number | null;
  sourceIds: string[];
  warnings: string[];
  unknowns: string[];
  needsReview: boolean;
  blockedByRetraction: boolean;
  contentTypeId?: string;
  customized?: boolean;
  /** Which Ideas run produced this variant (set by `apply`). */
  provenance?: { runId?: string; contextDigest?: string; policyEpoch?: number; model?: string };
  /** A regenerated version (for example after a voice change) waiting to be accepted. */
  proposedUpdate?: {
    text: string;
    voiceRevision: number | null;
    briefRevision: number;
    baseVariantRevision: number;
    unknowns: string[];
    warnings: string[];
    runId?: string;
  } | null;
}

export type SourcePolicy = 'public_quote' | 'rewrite_approval' | 'internal_reference' | 'prohibited';

export interface SnapshotSource {
  id: string;
  kind: string;
  title: string;
  text: string;
  active: boolean;
  visibility: string;
  reviewedAt?: string;
  sourcePolicy?: SourcePolicy | null;
  egressConsent?: ('local' | 'cloud')[];
  facts?: { id: string; text: string; approved: boolean }[];
}

export interface Phase2State {
  execution: string;
  trial: Trial;
  channels: { id: string; platform: string; account: string; displayState?: string }[];
  assets: Asset[];
  reviews: Review[];
  jobs: Job[];
}

export interface VoiceProfile {
  tone: 'warm' | 'direct' | 'reflective';
  writingExample: string;
  observations: string[];
  unknowns: string[];
}

export interface Speaker {
  id: string;
  label: string;
  revisions: { revision: number; profile: VoiceProfile; approvedAt: string; reason: string }[];
  activeRevision: number | null;
  provisional: VoiceProfile | null;
}

export type BrandMode = 'personal' | 'niche' | 'business' | 'hybrid';

/** Workspace content-type system projection (`content_types.projection`). Only the parts pages read. */
export interface ContentTypesView {
  catalogVersion: string;
  catalog: { id: string; version: string; label: string; description: string; recommendedFormatIds: string[]; preflightRuleIds: string[]; status: string }[];
  selection: { contentTypeId: string; contentTypeVersion: string; formatId: string | null };
  installedPacks: { id: string; version: string }[];
  packs: { id: string; version: string; label: string; entryCount: number; installedByDefault: boolean }[];
}

/** A BCP 47 locale tag from the shared catalogue (web/src/lib/locales), e.g. zh-Hant-HK or en-GB. Old data may say English / 繁體中文. */
export type LocaleTag = string;

/** Per-channel languages the person picked, the workspace default, and how they refer to themselves in gendered grammar. */
export interface LanguageSettings {
  default: LocaleTag | null;
  channels: Record<string, LocaleTag[]>;
  selfReference: 'feminine' | 'masculine' | 'neutral' | null;
  updatedAt?: number;
  updatedBy?: string;
}

export interface SnapshotState {
  workspace?: { id: string; name?: string; sample?: boolean };
  languageSettings?: LanguageSettings;
  session?: { completed?: boolean; step?: number };
  contentTypes?: ContentTypesView;
  speaker?: Speaker;
  brandHub?: { mode?: BrandMode | ''; purpose?: string; audience?: string; subject?: string; speaker?: string; layers?: string[] };
  phase2?: Phase2State;
  variants?: SnapshotVariant[];
  sources?: SnapshotSource[];
  [key: string]: unknown;
}

export interface Snapshot {
  revision: number;
  state: SnapshotState;
  membership?: Membership;
  runtimeResult?: Record<string, unknown>;
}

export interface Bootstrap extends Snapshot {
  workspaceId: string;
  auth?: { productionAccount: boolean };
}

/* ---------- ideas ---------- */

export interface SafeEvent {
  id: string;
  seq: number;
  type: string;
  at: number;
  text?: string;
  message?: string;
  destination?: number;
  sourceId?: string;
  policy?: string;
  stage?: string;
  percent?: number;
  variants?: number;
  /** `action.proposed`: which proposal (for example `schedule_plan`) and its time zone. */
  action?: string;
  timeZone?: string;
}

export interface RunVariant {
  platform: string;
  language: string;
  text: string;
  sourceIds: string[];
  unknowns: string[];
  warnings?: string[];
  candidateOnly?: boolean;
}

/** Candidate schedule proposed by the agent from channels and times named in the message (design §4.4). */
export interface SchedulePlanDestination {
  platform: string;
  language: string;
  localTime: string | null;
  assumed: boolean;
}

export interface SchedulePlan {
  kind: 'schedule';
  intent: string;
  timeZone: string;
  destinations: SchedulePlanDestination[];
  unsupported: string[];
  warnings: string[];
}

export interface Run {
  runId: string;
  conversationId: string;
  status: string;
  artifactHash: string | null;
  artifact: { variants: RunVariant[]; plan?: SchedulePlan | null } | null;
  usage: Record<string, unknown>;
  model: string;
  reasoning: string;
  events: SafeEvent[];
  cursor: number;
  /** A memory turn (a standing instruction) opens no run: `status` is `memory` and this carries the proposal. */
  memoryProposal?: MemoryProposal | null;
}

export interface Conversation {
  conversationId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  archived: boolean;
}

export interface Message {
  messageId: string;
  seq: number;
  role: 'user' | 'assistant' | 'system';
  body: Record<string, unknown>;
  runId: string | null;
  at: number;
}

export interface ModelOption {
  id: string;
  label: string;
  qualified: boolean;
  detail: string;
  /** Which runtime writes with it: undefined/`fixture` = PostRiff, `claude-code` = the local CLI. */
  route?: string;
  costClass?: 'none' | 'subscription' | 'paid' | string;
}

/** A CLI agent the API host can drive (agent chat design §4.2). Never carries the account's email. */
export interface AgentInfo {
  id: string;
  name: string;
  vendor?: string;
  installed: boolean;
  version: string | null;
  authStatus: 'ok' | 'missing' | 'unknown' | string;
  authMethod?: string | null;
  models: string[];
  modelsSource?: string;
  guidance?: string | null;
  host?: string;
  execution?: {
    budgetUsd: number;
    timeoutSeconds: number;
    tools: string;
    mcp: string;
    settingSources: string;
    sessionPersistence: boolean;
    environment: string[];
  };
}

export interface ModelCatalog {
  models: ModelOption[];
  reasoning: { id: string; available: boolean; detail: string }[];
  agents?: AgentInfo[];
}

/** One of the Markdown memory files rendered by the API (`GET /memory`). */
export interface MemoryFile {
  name: string;
  purpose: string;
  source: string;
  body: string;
  editHref: string | null;
}

/** Whether the managed cloud model may read the memory files (owner decision, audited). */
export interface MemoryEgress {
  cloud: boolean;
  decidedAt: number | null;
  decidedBy: string | null;
  sharedFiles: string[];
  shareablePrivacy: string[];
  /** Boundaries marked private, local-only or unlabelled: never sent, even with sharing on. */
  withheldBoundaries: number;
}

/** One learned preference (preference-learning design §6): about form only, scoped, under its own style revision. */
export interface LearnedItem {
  id: string;
  type: 'writing_preference' | 'working_style' | string;
  ruleKey: string;
  polarity: 'do' | 'avoid' | string;
  scope: { platform: string | null; language: string | null; contentTypeId: string | null };
  scopeKey: string;
  statement: string;
  applyWhen?: string;
  evidenceState: string;
  evidenceSummary?: string;
  source: string;
  status: 'active' | 'paused' | 'retired' | string;
  since?: string;
  retiredReason?: string;
}

/** `GET /memory` → `learning`: the settings, the style revision and every listed item. */
export interface LearningSummary {
  enabled: boolean;
  teamEdits: boolean;
  cloudExtraction: boolean;
  revision: number;
  resetAt: string | null;
  items: LearnedItem[];
  pendingProposals?: number;
}

/** A suggested change to the learned preferences. Only an owner decides it (`POST /memory/proposals/{id}/decide`). */
export interface MemoryProposal {
  id: string;
  status: 'pending' | 'remembered' | 'edited' | 'dismissed' | 'post_only' | 'expired' | string;
  op: 'add' | 'update' | 'retire' | string;
  source: string;
  at: number;
  expiresAt: number | null;
  decidedAt: number | null;
  type: string;
  ruleKey: string;
  polarity: string;
  scope: { platform: string | null; language: string | null; contentTypeId: string | null };
  scopeLabel: string;
  statement: string;
  applyWhen?: string;
  why?: string;
  evidence?: { variantId?: string; eventId?: string; revision?: number }[];
  variantId?: string | null;
  replaces?: string | null;
  /** How published posts with and without the feature did, like for like. An observation, never a cause. */
  performance?: PerformanceNote | null;
}

export interface PerformanceNote {
  metric: string;
  /** Posts are compared within one content type only (like for like). */
  contentTypeId?: string | null;
  withFeature: { posts: number; mean: number };
  withoutFeature: { posts: number; mean: number };
  direction: 'supports' | 'contradicts' | 'neutral' | string;
  note: string;
}

export interface MemoryProposals {
  pending: MemoryProposal[];
  recent: MemoryProposal[];
  versions: { id: string; scopeKey: string; body: LearnedItem; status: string; proposalId: string | null; validFrom: number; validTo: number | null }[];
  learning: LearningSummary;
  /** Per style revision: how much editing approved drafts needed (design §8.1). */
  stats?: { styleRevision: number; approvals: number; meanEditDistance: number; uneditedShare: number }[];
}

/** What a run received from learned preferences (`usage.memoryBindings`; the assistant turn's `memory`). */
export interface MemoryBinding {
  styleRevision: number;
  used: string[];
  statements: string[];
  omitted: string[];
}

/** Whether hosted drafts may look facts up on the web (owner decision). Always on when drafting on your own machine. */
export interface ResearchEgress {
  web: boolean;
  decidedAt: number | null;
  decidedBy: string | null;
  processors: string[];
  /** False when drafting on the person's own machine, where research is always on. */
  hosted: boolean;
  /** False when research is switched off for the whole deployment (POSTRIFF_RESEARCH=0): no switch applies. */
  enabled: boolean;
}

/* ---------- channels ---------- */

export type CapabilityLevel = 'Direct' | 'Assisted' | 'Bridge' | 'Unsupported';

export interface Capability {
  level: CapabilityLevel;
  evidence: string;
  verifiedAt: number | null;
  capabilityVersion: number;
}

export interface ChannelView {
  id: string;
  platform: string;
  account: string;
  accountType?: string;
  connectionState: string;
  capabilities: Record<string, Capability>;
  evidenceSource: string;
  scopes: string[];
  expiresAt?: number;
}

export interface ProviderView {
  id: string;
  platform: string;
  productionReviewed: boolean;
  capabilities: Record<string, boolean>;
}

export interface OAuthStart {
  transactionId: string;
  provider: string;
  platform: string;
  capability: string;
  scopes: string[];
  permissionExplanation: string;
  authorizeUrl: string;
  expiresAt: number;
}

export interface OAuthComplete {
  connected: boolean;
  reason?: string;
  account?: string;
  providerAccountId?: string;
  missingScopes?: string[];
  capabilities?: Record<string, Capability>;
  revision?: number;
}

/* ---------- usage & billing ---------- */

export interface Entitlement {
  planTermsId: string;
  writingBatchesRemaining: number;
  mediaCreditsRemaining: number;
  connectedAccounts: number;
  members: number;
  storageMb: number;
  resetsAt: number | null;
  source: string;
  version: number;
}

export interface SubscriptionView {
  planTermsId: string;
  provider: string;
  status: string;
  currentPeriodEnd: number | null;
  cancelAtPeriodEnd: boolean;
  graceUntil: number | null;
  plan: string;
  label: string;
  priceCents: number;
  currency: string;
  priceStatus: string;
  termsVersion: number;
  live: boolean;
}

export interface PlanTerms {
  id: string;
  plan: string;
  version: number;
  label: string;
  priceCents: number;
  currency: string;
  status: string;
  priceLabel: string;
  entitlements: Record<string, unknown>;
}

export interface LedgerEntry {
  kind: string;
  dimension: string;
  costState: string;
  estimatedUsdMicro: number;
  actualUsdMicro: number | null;
  at: number;
  provider: string;
  model: string;
}

export interface Usage {
  entitlement: Entitlement;
  subscription: SubscriptionView | null;
  budget: {
    windowKind: string;
    spentUsdMicro: number;
    reservedUsdMicro: number;
    warnUsdMicro: number;
    stopUsdMicro: number;
    status: string;
  };
  overage: string;
  ledger: LedgerEntry[];
  planTerms: PlanTerms[];
  note: string;
  lifecycle: { status: string; exportAvailable?: boolean; draftsRetained?: boolean; canPublish?: boolean };
  billing?: { provider: string; checkoutAvailable: boolean; portalAvailable: boolean };
  membership: Membership;
}

/* ---------- analytics & audience ---------- */

export interface Metric {
  value: number | null;
  display: string;
  availability: string;
  unit: string;
  nativeName: string;
}

export interface AnalyticsPost {
  provider: string;
  providerPostId: string;
  jobId: string | null;
  platform: string | null;
  language: string | null;
  publishedState: string;
  contentOrigin: string;
  metrics: Record<string, Metric>;
  freshness: { observedAt: number; ingestedAt: number };
  definitionVersion: string;
  rates: Record<string, { display: string; numerator: number | null; denominator: number | null }>;
}

export interface Analytics {
  state: string;
  posts: AnalyticsPost[];
  rules: Record<string, string>;
  connections: { id: string; platform: string; account: string; analytics: string }[];
  freshnessNow: number;
}

export interface Thread {
  threadId: string;
  connectionId: string;
  provider: string;
  providerPostId: string;
  commentId: string;
  author: string;
  text: string;
  ingestedAt: number;
  tombstoned: boolean;
  replyAvailable: boolean;
  replyLevel: string;
}

export interface Audience {
  threads: Thread[];
  capabilities: { connectionId: string; commentsRead: string }[];
  limits: string;
}

/* ---------- members, invitations, sessions, audit, privacy ---------- */

export interface Member extends Membership {
  userId: string;
  status: string;
  you: boolean;
  updatedAt: number;
}

export interface Invitation {
  invitationId: string;
  email: string;
  role: string;
  permissions: Record<string, boolean>;
  createdBy: string;
  createdAt: number;
  expiresAt: number;
  acceptedBy: string | null;
  state: 'pending' | 'accepted' | 'revoked' | 'expired';
}

export interface InvitationCreated {
  invitationId: string;
  token: string;
  role: string;
  expiresAt: number;
  emailSent?: boolean;
}

export interface SessionInfo {
  sessionId: string;
  firstSeen: number;
  lastSeen: number;
  client: string;
  revoked: boolean;
  current: boolean;
}

export interface AuditEvent {
  id?: string;
  kind: string;
  actor: string;
  subject: string;
  meta: Record<string, unknown>;
  at: number;
}

export interface DataRequest {
  requestId: string;
  kind: string;
  status: string;
  receipt: Record<string, unknown>;
  requestedAt: number;
}

export interface PrivacyNotice {
  schema: string;
  status: string;
  aiProcessing: string;
  providerAccess: string;
  ingestion: string;
  retention: Record<string, { retention: string; note: string }>;
  subprocessors: { name: string; purpose: string; status: string; region?: string }[];
  rights: string[];
  telemetry: string;
}

export interface Health {
  status: string;
  execution: string;
  configured: boolean;
}
