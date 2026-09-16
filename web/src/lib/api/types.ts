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
  /** A regenerated version (for example after a voice change) waiting to be accepted. */
  proposedUpdate?: {
    text: string;
    voiceRevision: number | null;
    briefRevision: number;
    baseVariantRevision: number;
    unknowns: string[];
    warnings: string[];
  } | null;
}

export interface SnapshotSource {
  id: string;
  kind: string;
  title: string;
  text: string;
  active: boolean;
  visibility: string;
  reviewedAt?: string;
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

export interface SnapshotState {
  workspace?: { id: string; name?: string; sample?: boolean };
  session?: { completed?: boolean; step?: number };
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

export interface Run {
  runId: string;
  conversationId: string;
  status: string;
  artifactHash: string | null;
  artifact: { variants: RunVariant[] } | null;
  usage: Record<string, unknown>;
  model: string;
  reasoning: string;
  events: SafeEvent[];
  cursor: number;
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

export interface ModelCatalog {
  models: { id: string; label: string; qualified: boolean; detail: string }[];
  reasoning: { id: string; available: boolean; detail: string }[];
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
