/**
 * Typed contracts for the hosted PostRiff API (Python, served at /api/*).
 * Ported from the founder alpha client (`studio/web/src/founder/cloud-api.ts`)
 * and kept in one place so every page reads the same shapes.
 */
import type { WorkspacePlan, WorkspaceRole } from '@/types';

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
  /** Summary for the profile page and switcher (`hosted.workspace_summary`). */
  name: string;
  /** `trial` until a subscription is live; then the paid plan. */
  plan: WorkspacePlan;
  trialPlan: 'studio' | 'assist' | null;
  owner: { userId: string; displayName: string } | null;
  memberCounts: Record<WorkspaceRole, number>;
}

/* ---------- workspace snapshot (single mutation channel: POST /actions) ---------- */

export interface Asset {
  sourceHash?: string;
  decoder?: string;
  processing?: string;
  createdAt?: number;
  uploadedBy?: string;
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
  /** The connection this post goes out through (a `ChannelView.id`). */
  channelId?: string;
  account: string;
  platform: string;
  operation: string;
  variantId: string;
  contentRevision: number;
  payload: { text: string; language: string };
  media: (Asset & { alt: string })[];
  timing: { local: string; timeZone: string; utc: string; timestamp?: number; fold?: number };
  voiceRevision?: number | null;
  styleRevision?: number;
  payloadDigest?: string;
  providerAccountId?: string;
  expiresAt: number;
  idempotencyKey: string;
  execution: string;
}

export interface Job {
  id: string;
  manifest: Manifest;
  state: string;
  approvedBy?: string;
  approvedAt?: number;
  approvalDigest?: string;
  nextAt?: number;
  checks?: number;
  scheduleId?: string | null;
  url?: string;
  events: { at: number; state: string; message: string; execution?: string }[];
  attempts: { number: number; startedAt: number; endedAt?: number }[];
  container?: string;
  resultSchema?: string;
  progress?: { version: number; stage: string };
  providerReference?: string;
  providerConfirmed?: string;
  nextAction?: string;
  cancelRequested: boolean;
  verification?: { method: string; at: number } | null;
}

export interface Review {
  createdAt?: number;
  jobId?: string;
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

export interface VariantRevision {
  revision: number;
  text: string;
  /** `ideas-candidate`, `fixture`, `author-edit`, `chosen-opening`, `accepted-fixture-replacement`. */
  origin: string;
  /** ISO string from `domain.py` `now()`; absent on Ideas candidates. */
  at?: string | number | null;
}

export interface VariantFeedback {
  id: string;
  reasons: string[];
  note: string;
  actor: string;
  /** Epoch seconds (`store.py`). */
  at: number;
  revision: number;
}

export interface SnapshotVariant {
  revisions?: VariantRevision[];
  rejected?: boolean;
  feedback?: VariantFeedback[];
  runId?: string;
  id: string;
  platform: string;
  language: string;
  /** The connection this draft was written for; absent on platform-level drafts. */
  channelId?: string;
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
  provenance?: { runId?: string; contextDigest?: string; policyEpoch?: number; model?: string; derivedFrom?: string };
  /** Later runs that refreshed this unscheduled draft in place (most recent last). */
  runRefs?: string[];
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

export interface SourceFact {
  id: string;
  text: string;
  approved: boolean;
  locator?: string;
}

/** Where a web-research page came from (`ideas._research`). */
export interface SourceOrigin {
  kind: string;
  url?: string;
  host?: string;
  query?: string;
  published?: string;
  fetchedAt?: string;
}

export interface SourceUseApproval {
  actor?: string;
  at?: number | string;
  factsDigest?: string;
}

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
  facts?: SourceFact[];
  createdAt?: string | number;
  withdrawnAt?: string | number;
  unknowns?: string[];
  origin?: SourceOrigin | null;
  useApprovals?: SourceUseApproval[];
  /** Voice-sample fields are present only when `kind === 'voice_sample'`. */
  voiceOrigin?: 'user_provided' | 'official_api';
  provider?: string;
  externalPostId?: string;
  permalink?: string | null;
  mediaType?: string;
  thumbnailUrl?: string | null;
  importedAt?: number;
  sourceCoverage?: { selectionOnly: boolean; verifiedPages: number; providerPage: Record<string, unknown> };
  connectionId?: string;
  providerAccountId?: string;
  selected?: boolean;
  revision?: number;
  contentHash?: string;
  platform?: string;
  account?: string;
  language?: string;
  publishedAt?: string;
  label?: 'representative' | 'outdated' | 'sponsored' | 'guest' | 'ai_generated' | null;
  partialCoverage?: boolean;
  purposeGrants?: ('analysis' | 'generation')[];
  routeGrants?: string[];
  useGrants?: { purpose: 'analysis' | 'generation'; route: string }[];
  cleanupStatus?: string;
}

/** A saved account group (Rafii v9 Channel Bloom): a batch-selection shortcut keyed by connection ids. */
export interface ChannelFolder {
  id: string;
  name: string;
  symbol: 'folder' | 'spark' | 'music' | 'briefcase' | 'heart' | 'globe' | string;
  pinned: boolean;
  /** `Phase2State.channels[].id` values; a removed connection stays listed so the person can see it. */
  accountIds: string[];
  createdAt?: number;
  createdBy?: string;
  updatedAt?: number;
  updatedBy?: string;
}

export interface Phase2State {
  execution: string;
  trial: Trial;
  channels: { id: string; platform: string; account: string; displayState?: string; revoked?: boolean }[];
  assets: Asset[];
  reviews: Review[];
  jobs: Job[];
  /** Absent on workspaces that never saved a folder. Changed only through `p2_folder_save|delete|move`. */
  channelFolders?: ChannelFolder[];
}

export interface VoiceProfile {
  packageSchema?: string;
  fields?: Record<string, unknown>[];
  tone: 'warm' | 'direct' | 'reflective' | null;
  writingExample: string;
  observations: string[];
  unknowns: string[];
  status?: 'proposed' | 'stale';
  staleReason?: string;
  analysisRoute?: string;
  analysisMethod?: 'local-rules' | 'ai';
  analysisModel?: string;
  analysisProvider?: string;
  evidenceSourceIds?: string[];
  dimensions?: {
    id: string;
    observation: string;
    support: string[];
    counterEvidence: string[];
    quotes?: { sourceId: string; text: string }[];
    evidenceLevel: 'limited' | 'supported' | 'conflicting' | 'insufficient';
  }[];
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
  you?: { identitySentence?: string; [key: string]: unknown };
  brandHub?: { mode?: BrandMode | ''; purpose?: string; audience?: string; subject?: string; speaker?: string; layers?: string[] };
  phase2?: Phase2State;
  variants?: SnapshotVariant[];
  sources?: SnapshotSource[];
  raffi?: {
    campaignPlanning?: {
      campaigns: RaffiCampaign[];
      recurringTasks: RecurringTask[];
      occurrences: RecurringOccurrence[];
    };
    /** When suggestions were last recomputed (epoch seconds); absent until the first check. */
    suggestionsCheckedAt?: number;
    suggestions?: { id: string; kind: string; reason: string; status: string; evidence: { type: string; id: string; revision: number }[]; action: string; actionRef?: { id: string; type: string; authority: string; workspaceId?: string; targetType?: string; targetId?: string; targetRevision?: number } | null }[];
  };
  [key: string]: unknown;
}

/** A campaign brief; an automation owns one (`kind: 'automation'`), older campaigns may have none. */
export interface RaffiCampaign {
  id: string;
  version: number;
  goal: string;
  audience: string;
  facts: Record<string, string>;
  status: string;
  missingFacts: string[];
  kind?: 'automation' | string;
  items: { id: string; occurrenceId?: string; conversationId?: string; runId?: string; status?: string; needsReview?: boolean }[];
  createdAt?: number;
  updatedAt?: number;
}

/** One place an automation drafts for: a platform in a language, optionally a connected account. */
export interface RecurringDestination {
  platform: string;
  language: string;
  channelId?: string;
}

/** One weekly slot: a weekday and its own local time (orchestration §1). */
export interface ScheduleSlot {
  weekday: string;
  localTime: string;
}

export interface RecurringSchedule {
  /** Absent means weekly. `once` runs on one date (`date` + `localTime`). */
  kind?: 'weekly' | 'monthly' | 'countdown' | 'once' | string;
  /** Weekly: one or more weekday names. Older tasks carry a single `weekday`. With `slots`, these mirror the first slot. */
  weekdays?: string[];
  weekday?: string;
  /** Weekly slots, each with its own time; when present they win over `weekdays` + `localTime`. */
  slots?: ScheduleSlot[];
  /** Once: the date (YYYY-MM-DD) of the single run. */
  date?: string;
  /** Monthly: days 1–31 or "last". */
  monthDays?: (number | 'last')[];
  /** Countdown: the event date (YYYY-MM-DD) and the days before it that get a run. */
  eventDate?: string;
  daysBefore?: number[];
  /** Triggers (`on_new_source`, `on_strong_post`): what starts a run and how many a day. */
  sourceKinds?: string[];
  maxPerDay?: number;
  withinDays?: number;
  /** Absent for triggers. */
  localTime?: string;
  timeZone: string;
}

/* ---------- automation workflow (orchestration §1–§3, authorityVersion 3) ---------- */

/** When one stage of a run happens. Weekday specs resolve to the first such local time after drafting; the rest
 *  resolve against the anchor (the schedule's own instant). */
export type AutomationWhen =
  | { at: 'anchor' }
  | { at: 'generate' }
  | { asap: true }
  | { minutesOffset: number }
  | { dayOffset: number; localTime: string }
  | { weekday: string; localTime: string };

/** How drafts reach the platforms: `auto` publishes eligible drafts, `review` waits for an approval, `drafts` never publishes. */
export type PublishPolicy = 'auto' | 'review' | 'drafts';

export interface AutomationResearch {
  query: string;
  about: string;
  /** Allowed publisher hosts (subdomains included); empty means any reputable publisher. */
  domains: string[];
  /** The person's own words ("reputable science publications"). */
  publications: string;
  urls: string[];
  recencyDays: number;
  minScore: number;
  /** `skip` (default): no filler when nothing clears the bar. */
  onNothing: 'skip' | 'draft_without' | string;
  quote: { about: string } | null;
}

export interface AutomationWorkflow {
  version: number;
  /** null until the person chooses; such an automation cannot be activated. */
  policy: PublishPolicy | null;
  stages: { generate: AutomationWhen; review: AutomationWhen | null; publish: AutomationWhen | null };
  research: AutomationResearch | null;
  content: { task: string; instructions: string };
  /** Per-platform adaptation the person asked for, e.g. `{X: "shorter, sharper"}`. */
  platformNotes: Record<string, string>;
}

/** The owner's standing authority to auto-publish (set only on activation of an `auto` workflow). */
export interface PublishAuthority {
  grantedBy: string;
  grantedAt: number;
  definitionDigest: string;
  /** Posts built on sources Raffi found may publish without a per-source review. */
  sourceUse: boolean;
}

/** A run's generation stage (`lifecycle.RUN_STAGES`). */
export type AutomationRunStage = 'planned' | 'researching' | 'drafting' | 'drafted' | 'skipped' | 'source_unavailable' | 'failed';
/** One destination's state (`lifecycle.ITEM_STATES`). */
export type AutomationItemState =
  | 'ready_for_review'
  | 'needs_revision'
  | 'approved'
  | 'scheduled'
  | 'publishing'
  | 'published'
  | 'rejected'
  | 'skipped'
  | 'failed'
  | 'platform_disconnected'
  | 'approval_expired';

export interface RunStages {
  generateAt: number;
  reviewAt: number | null;
  publishAt: number | null;
  /** Local ISO times in the schedule's zone. */
  local?: { generate: string; review: string | null; publish: string | null };
}

export interface RunResearchCandidate {
  url: string;
  title: string;
  host: string;
  published?: string | null;
  score?: number;
  reasons?: string[];
}

export interface RunResearch {
  query?: string;
  domains?: string[];
  candidates?: RunResearchCandidate[];
  chosen: (RunResearchCandidate & { sourceId?: string | null }) | null;
  decision: 'chosen' | 'nothing_worth' | 'unavailable' | 'skipped_by_rule' | string;
  /** Plain-language reason for the decision. */
  reason?: string;
  quote?: { text: string; author: string; verified: boolean; hosts?: string[] } | null;
}

export interface RunSkill {
  skill: string;
  status: 'done' | 'skipped' | 'failed' | 'waiting' | string;
  at?: number;
  detail?: string;
}

export interface RunItemDecision {
  decision: 'approve' | 'reject' | 'revise' | string;
  by: string;
  at: number;
  note?: string;
  variantRevision?: number;
  textDigest?: string;
  excludedUnknowns?: string[];
  acknowledgedWarnings?: string[];
  sourceUse?: { sourceId: string; factsDigest: string }[];
}

/** One destination of a run (orchestration §2). */
export interface RunItem {
  /** `<platform>|<channelId or ''>|<language>`. */
  key: string;
  platform: string;
  channelId?: string | null;
  account?: string;
  language: string;
  variantId?: string | null;
  variantRevision?: number | null;
  textDigest?: string | null;
  state: AutomationItemState | string;
  /** Plain-language reason for alternate states (held back, disconnected, failed…). */
  reason?: string | null;
  publishAt?: number | null;
  capability?: { publish: boolean; reason: string };
  decision?: RunItemDecision | null;
  approvedVia?: 'human' | 'owner_preauthorization' | string | null;
  reviewId?: string | null;
  jobId?: string | null;
  attempts?: number;
  lastError?: string | null;
  changedAt?: number;
}

/** A recurring draft-preparation task (an Automation). Before authority 3 it only drafts; a v3 `workflow` says
 *  whether and when drafts publish. */
export interface RecurringTask {
  id: string;
  campaignId: string;
  version: number;
  status: 'draft' | 'active' | 'paused' | 'cancelled' | string;
  name?: string;
  route?: string;
  reasoning?: 'quick' | 'standard' | 'deep' | string;
  maxCostUsdMicro?: number;
  pauseReason?: string;
  schedule: RecurringSchedule;
  /** `scheduledFor` is the next generation instant; `anchorAt` (v3) the schedule instant it belongs to. */
  nextOccurrence?: { scheduledFor?: number; anchorAt?: number; local: string; utc: string; offset: string };
  /** Authority 2 (Automations); older tasks have one LinkedIn `destination`. */
  authorityVersion?: number;
  destinations?: RecurringDestination[];
  destination?: RecurringDestination;
  destinationLabel?: string | null;
  accountLabels?: Record<string, string>;
  contentType?: { contentTypeId: string; contentTypeVersion: string; formatId: string | null } | null;
  contentLabel?: string | null;
  contentLibrary?: { editorialId: string; nativeId: string } | null;
  contextSourceIds?: string[];
  /** Personalized drafts use the workspace's writing samples allowed for this writer (part of the definition). */
  voiceMode?: 'neutral' | 'personalized' | string;
  limits?: { draftsPerOccurrence: number };
  /** Extra context each run reads (part of the activated definition). */
  include?: { recentPostsDays?: number; evergreen?: { minAgeDays: number } } | null;
  /** Triggers: events waiting to run, and how many a daily limit skipped. */
  pendingEvents?: { id: string; kind: string; at: number }[];
  skippedEvents?: number;
  /** Members who asked for a "drafts ready" email (outside the definition). */
  emailWatchers?: string[];
  createdBy?: string;
  createdAt?: number;
  updatedAt?: number;
  activatedBy?: string;
  activatedAt?: number;
  /** v3: the authorized workflow (null for a drafts-only automation built in the builder). */
  workflow?: AutomationWorkflow | null;
  /** v3: the person's request in their words (display only). */
  intent?: string | null;
  publishAuthority?: PublishAuthority | null;
  /** Epoch seconds: a pause that resumes on its own. */
  pausedUntil?: number | null;
  /** A deleted automation is cancelled and hidden from lists; its run history is kept. */
  deletedAt?: number | null;
  deletedBy?: string | null;
  lastAnchorAt?: number | null;
  /** v3: the local ISO time of the next publish (display only). */
  nextPublish?: string | null;
}

export interface RecurringOccurrence {
  id: string;
  taskId: string;
  taskVersion?: number;
  state: 'pending' | 'running' | 'completed' | 'failed' | 'held' | 'missed' | 'cancelled' | string;
  scheduledFor: number;
  reason?: string;
  runId?: string;
  conversationId?: string;
  completedAt?: number;
  skippedDestinations?: { platform: string; channelId?: string; account?: string }[];
  draftCount?: number;
  /** What started a trigger run: a new idea/link/document, or a strong post (observation). */
  event?: { id: string; kind: 'new_source' | 'strong_post' | string; title?: string; sourceId?: string; platform?: string; publishedAt?: string; metric?: string; value?: number; typical?: number; sampleSize?: number };
  /** The older post an evergreen run refreshed ({} when none was old enough). */
  evergreen?: { jobId?: string; platform?: string; publishedAt?: string };
  /** What the run's writer charged, in micro-dollars (0 for free routes). */
  costUsdMicro?: number;
  /** Set when someone opened or dismissed the drafts ("drafts ready" clears). */
  seenAt?: number;
  seenBy?: string;
  /* v3 runs (orchestration §2); `state` above stays the projected generation state. */
  anchorAt?: number;
  policy?: PublishPolicy | string;
  stages?: RunStages;
  lifecycle?: AutomationRunStage | string;
  research?: RunResearch | null;
  skills?: RunSkill[];
  items?: RunItem[];
  history?: { at: number; event: string; detail?: string; actor?: string }[];
  notices?: { reviewSentAt?: number | null; expiredSentAt?: number | null; disconnectedSentAt?: number | null };
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
  images?: number;
  /** `action.proposed`: which proposal (for example `schedule_plan`) and its time zone. */
  action?: string;
  timeZone?: string;
}

export interface RunVariant {
  platform: string;
  language: string;
  /** Account identity carried from the destination (v9 §4); absent for platform-level requests. */
  channelId?: string;
  account?: string;
  text: string;
  sourceIds: string[];
  unknowns: string[];
  warnings?: string[];
  candidateOnly?: boolean;
}

export interface GeneratedImage {
  id: string;
  hash: string;
  mime: string;
  width?: number;
  height?: number;
  bytes?: number;
  alt?: string;
}

/** Candidate schedule proposed by the agent from channels and times named in the message (design §4.4). */
export interface SchedulePlanDestination {
  platform: string;
  language: string;
  channelId?: string;
  localTime: string | null;
  assumed: boolean;
}

/** One drafting destination as the composer sends it: an account when one is selected, else a platform. */
export interface Destination {
  platform: string;
  language: LocaleTag;
  channelId?: string;
}

export interface SchedulePlan {
  kind: 'schedule';
  intent: string;
  timeZone: string;
  destinations: SchedulePlanDestination[];
  unsupported: string[];
  warnings: string[];
}

/** Server estimate for the exact request a credit quote would bind (FINAL-05). */
export interface CreditEstimate {
  estimateMilliCredits: number;
  ceilingMilliCredits: number;
  availableMilliCredits: number;
  basis: string;
  model: string;
  provider: string;
  policy: string;
  reasoning?: string;
}

export interface Run {
  runId: string;
  conversationId: string;
  status: string;
  artifactHash: string | null;
  artifact: { variants: RunVariant[]; plan?: SchedulePlan | null; images?: GeneratedImage[]; imageModel?: string; reworkOf?: string } | null;
  usage: Record<string, unknown>;
  model: string;
  reasoning: string;
  events: SafeEvent[];
  cursor: number;
  /** A memory turn (a standing instruction) opens no run: `status` is `memory` and this carries the proposal. */
  memoryProposal?: MemoryProposal | null;
  /** A request for recurring drafts opens no run: `status` is `automation`, this is the automation Rafii set up
   *  (null when it could not), and `reply` is Rafii's answer in the conversation. */
  automation?: ChatAutomation | null;
  reply?: string;
}

/** The automation a chat request set up (server `automation_chat.card`): what Rafii understood and what is left. */
export interface ChatAutomation {
  taskId: string;
  campaignId: string;
  name: string;
  status: 'active' | 'draft' | string;
  goal: string;
  audience: string;
  schedule: RecurringSchedule;
  /** "Every Tuesday at 09:00 (Asia/Hong_Kong)". */
  scheduleText: string;
  nextOccurrence?: RecurringTask['nextOccurrence'] | null;
  /** "Tuesday 29 September at 09:00", or null for a trigger. */
  firstRun?: string | null;
  destinations: (RecurringDestination & { account?: string })[];
  contentLabel?: string | null;
  voiceMode: 'neutral' | 'personalized' | string;
  sources: { id: string; title: string }[];
  /** Decisions left before it can run: an owner, a per-run spending limit, missing facts. */
  needs: { code: 'owner' | 'spend' | 'facts' | 'review' | string; text: string }[];
  /** What Rafii had to assume ("No time was named, so …"). */
  notes: string[];
  /* Orchestration §7: every field below is optional so older messages still render as before. */
  workflow?: AutomationWorkflow | null;
  policy?: PublishPolicy | null;
  /** The stages in plain words: `{step: 'generate'|'review'|'publish', when: 'Wednesday 9:00 AM', text}`. */
  plan?: { step: string; when: string; text: string }[];
  /** Each platform named, with whether PostRiff can publish to it and why not. */
  platforms?: { platform: string; account?: string; canPublish: boolean; reason: string }[];
  /** A question Rafii still needs answered; the next message (or a quick reply) answers it. */
  pending?: { taskId: string; question: 'policy' | 'review_time' | string } | null;
  /** Answers the person can send as their next message. */
  quickReplies?: string[];
  /** The latest runs with their status. */
  runs?: { id: string; status: string; label?: string; scheduledFor?: number; anchorAt?: number; publishAt?: number | null; attention?: boolean }[];
  /** The model tier that read the request (not shown). */
  tier?: string;
  /** An explain turn: what Rafii looked at to answer. */
  explain?: { about?: string; question?: string; text?: string; lines?: string[] } | null;
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
  provider?: string;
  egress?: 'local' | 'cloud';
  voiceRoute?: string;
  /** The class grant that also covers voiceRoute (every Rafii AI writer model), if any. */
  voiceRouteClass?: string | null;
  voiceAnalysisAvailable?: boolean;
  reasoning?: { id: string; available: boolean; detail: string }[];
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
  probedAt?: number;
  reasoning?: { id: string; available: boolean; detail: string }[];
  guidance?: string | null;
  host?: string;
  execution?: {
    budgetUsd: number | null;
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
  imageGeneration?: {
    available: boolean;
    model: string | null;
    provider: string | null;
    costClass: 'paid';
    independentOfWritingModel: true;
    detail: string;
  };
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
  extractor?: { kind: 'rules' | 'local' | 'cloud'; egress?: 'rules' | 'local' | 'cloud'; model: string | null; allowed: boolean };
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
  recentTotal?: number;
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
  socialReadiness?: { connection: string; history: string; publishing: string; fullyAvailable: boolean; evidence: string; liveVerified: boolean };
  capabilities: Record<string, Capability>;
  evidenceSource: string;
  scopes: string[];
  expiresAt?: number;
  /** SHA-256 of the account's stored profile picture; null when the provider gave none. */
  pictureDigest?: string | null;
}

export interface ProviderView {
  configurationState?: string;
  credentialPresence?: { clientId: boolean; clientSecret: boolean };
  readinessState?: string;
  publicConnectionReady?: boolean;
  liveVerified?: boolean;
  reviewStatus?: string;
  reviewNote?: string;
  configured?: boolean;
  connectReady?: boolean;
  setupIssues?: string[];
  callbackUri?: string | null;
  accountRequirement?: string;
  historyAvailableForApp?: boolean;
  commentsReadImplemented?: boolean;
  id: string;
  platform: string;
  productionReviewed: boolean;
  executionPaused?: boolean;
  capabilities: Record<string, boolean>;
  /** 'oauth' redirects to the platform; 'bot_code' means posting a one-time code where Rafii's bot sees it (Telegram). */
  connectKind?: 'oauth' | 'bot_code';
  /** One value to ask before connecting: a Bluesky handle or a Mastodon server. */
  startInput?: { name: string; label: string; placeholder?: string } | null;
  /** A destination (a Discord channel) is chosen after connecting. */
  hasDestinations?: boolean;
}

export interface ChannelDestination {
  id: string;
  name: string;
  kind: 'text' | 'announcement';
  selected: boolean;
}

export interface OwnedPost {
  id: string;
  externalPostId?: string;
  provider?: string;
  providerAccountId?: string;
  text: string;
  platform: string;
  publishedAt: string;
  permalink: string | null;
  thumbnailUrl: string | null;
  mediaType?: string;
}

export interface OwnedPostPage {
  connectionId: string;
  providerAccountId: string;
  receipt: string;
  expiresAt: number;
  posts: OwnedPost[];
  coverage?: { startedFromBeginning: boolean; endReached: boolean; from: string | null; to: string | null; undatedCount: number; eligibleCount: number };
  nextCursor: string | null;
  scannedCount: number;
  skippedCount: number;
  partialCoverage: boolean;
  coverageNote: string;
}

export interface OAuthStart {
  transactionId: string;
  provider: string;
  platform: string;
  capability: string;
  scopes: string[];
  permissionExplanation: string;
  /** Null for a bot-code connection (Telegram), which never leaves Rafii. */
  authorizeUrl: string | null;
  expiresAt: number;
  connectKind?: 'oauth' | 'bot_code';
  /** Bot-code connections: the code to post, the bot to add and the steps. */
  code?: string;
  botUsername?: string;
  instructions?: string[];
}

export interface OAuthComplete {
  connectionId?: string;
  connected: boolean;
  /** Bot-code connections before the code has been seen in a channel. */
  pending?: boolean;
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
  chargeBatch?: boolean;
  reservationId?: string | null;
  runId?: string | null;
  jobId?: string | null;
  kind: string;
  dimension: string;
  costState: string;
  estimatedUsdMicro?: number;
  actualUsdMicro?: number | null;
  at: number;
  provider: string;
  model: string;
}

export interface CreditBalance {
  mode: "credits";
  availableMilliCredits: number;
  heldMilliCredits: number;
  usedMilliCredits: number;
  debtMilliCredits: number;
  quoteType: "spending_limit";
  textOnly: boolean;
}

export interface Usage {
  credits?: CreditBalance | null;
  entitlement: Entitlement;
  subscription: SubscriptionView | null;
  budget: {
    windowKind: string;
    spentUsdMicro: number;
    reservedUsdMicro: number;
    warnUsdMicro: number;
    stopUsdMicro: number;
    status: string;
  } | null;
  overage: string;
  ledger: LedgerEntry[];
  planTerms: PlanTerms[];
  note: string;
  lifecycle: { status: string; exportAvailable?: boolean; draftsRetained?: boolean; canPublish?: boolean };
  billing?: { provider: string; checkoutAvailable: boolean; portalAvailable: boolean };
  membership: Membership;
}

/* ---------- time back (time_savings.py) ---------- */

/** Atomic tasks Time Back counts. `campaign_plan` has a default but no completion boundary yet. */
export type TimeSavingsTaskKind = 'draft' | 'adapt' | 'publish' | 'campaign_plan' | 'recurring_setup';
/** Provenance of a saving: Rafii's defaults, the person's own answers, or measured active time in Rafii. */
export type TimeSavingsConfidence = 'estimated' | 'personalized' | 'measured';
export type TimeSavingsRange = '7d' | '30d' | 'year' | 'all';
export type TimeSavingsBaselineSource = 'raffi_default' | 'personalized' | 'user_override';

export interface TimeSavingsBreakdown {
  taskKind: TimeSavingsTaskKind;
  savedSeconds: number;
  /** Whole minutes to display; the parts add up exactly to `totalMinutes`. */
  minutes: number;
  count: number;
}

export interface TimeSavingsBaseline {
  taskKind: TimeSavingsTaskKind;
  seconds: number;
  source: TimeSavingsBaselineSource;
  samples: number;
  defaultSeconds: number;
  /** What applies without an explicit setting: personalized once there are enough answers, else the default. */
  automaticSeconds: number;
}

export interface TimeSavingsCalibration {
  /** Task kinds the person may be asked about now (after completed work, at most once a month each). */
  due: TimeSavingsTaskKind[];
  baselines: TimeSavingsBaseline[];
  personalizeAfter: number;
}

export interface TimeSavingsSummary {
  range: TimeSavingsRange;
  since: number | null;
  until: number;
  /** `empty` means nothing completed yet: show that, never "0h". */
  state: 'ready' | 'empty';
  totalSavedSeconds: number;
  totalMinutes: number;
  completedTasks: number;
  basis: TimeSavingsConfidence | null;
  breakdown: TimeSavingsBreakdown[];
  confidence: Record<TimeSavingsConfidence, number>;
  calculatorVersion: string;
  hasCalibrationPrompt: boolean;
  calibration: TimeSavingsCalibration;
}

/** A cumulative, idempotent heartbeat: aggregate seconds only, never what was typed or clicked. */
export interface ActiveTimeBeat {
  clientSessionKey: string;
  workflowKey: string;
  taskKind: TimeSavingsTaskKind;
  activeSeconds: number;
  sequence: number;
  closed?: boolean;
}

export type TimeSavingsCalibrationInput =
  | { taskKind: TimeSavingsTaskKind; source: 'prompt'; manualSeconds: number }
  | { taskKind: TimeSavingsTaskKind; source: 'prompt'; dismissed: true }
  | { taskKind: TimeSavingsTaskKind; source: 'settings_override'; manualSeconds: number }
  | { taskKind: TimeSavingsTaskKind; source: 'settings_override'; clear: true };

/* ---------- analytics & audience ---------- */

export interface Metric {
  value: number | null;
  display: string;
  availability: string;
  unit: string;
  nativeName: string;
}

export interface AnalyticsPost {
  connectionId?: string | null;
  contentTypeId?: string | null;
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
  families?: Record<string, string[]>;
  state: string;
  posts: AnalyticsPost[];
  rules: Record<string, string>;
  connections: { id: string; platform: string; account: string; analytics: string }[];
  freshnessNow: number;
}

export interface ReplyRecord {
  draftId: string;
  status: string;
  text: string;
  origin?: string;
  label?: string;
  updatedAt?: number | null;
  requiresReconfirmation?: boolean;
}

export interface Thread {
  replies?: ReplyRecord[];
  permalink?: string | null;
  createdAtProvider?: number | null;
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
  counts?: { all?: number; replied?: number; unanswered?: number };
  replySendingEnabled?: boolean;
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
  displayName: string;
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

/** The signed-in person (`GET /api/me`). Name, email and avatar come from the auth provider. */
export interface Me {
  userId: string;
  displayName: string;
  sessionId: string | null;
  mfa: {
    /** False for identities without assurance levels (the dev harness). */
    available: boolean;
    /** Once true the API refuses this user's sessions until a second factor is presented. */
    enforced: boolean;
    enforcedAt: number | null;
    aal: 'aal1' | 'aal2' | null;
  };
  /** Person-level preferences; empty strings mean "follow this device". */
  preferences: { timeZone: string; locale: string; alertNewDevice: boolean };
}

/** Body of `PATCH /api/me`; only the keys present change. */
export interface ProfileChanges {
  displayName?: string;
  timeZone?: string;
  locale?: string;
  alertNewDevice?: boolean;
}

/** One connected channel in one of the user's workspaces (`GET /api/me/channels`). Read-only. */
export interface MyChannel {
  workspaceId: string;
  workspaceName: string;
  id: string;
  platform: string;
  account: string;
  accountType?: string | null;
  connectionState: string;
  expiresAt?: number | null;
  verifiedAt?: number | null;
  evidenceSource: string;
  /** Whether the user holds `manage_connections` in that workspace. */
  canManage: boolean;
  /** Who connected it, from the audit trail; null for channels with no recorded connection event. */
  connectedBy: { userId: string; displayName: string; at: number } | null;
}

/**
 * One line of the person's account history (`GET /api/me/security-events`): their own security
 * actions, first sign-ins per device (`session.started`), and changes others made to their
 * memberships. Newest first.
 */
export interface SecurityEvent {
  id: string;
  kind: string;
  subject: string;
  at: number;
  meta: Record<string, unknown>;
  workspaceId: string | null;
  workspaceName: string;
}

/** An invitation addressed to the person's verified email (`GET /api/me/invitations`). */
export interface PendingInvitation {
  invitationId: string;
  workspaceId: string;
  workspaceName: string;
  role: string;
  permissions: Record<string, boolean>;
  invitedBy: { userId: string; displayName: string };
  createdAt: number;
  expiresAt: number;
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
  completedAt?: number | null;
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

/* ---------- public tool registry ---------- */

export interface ToolBounds {
  maxSeconds: number;
  maxInputBytes: number;
  maxOutputBytes: number;
  network: string;
  files: string;
}

export interface ToolDefinition {
  id: string;
  version: string;
  effect: string;
  cost: string;
  purpose: string;
  bounds: ToolBounds;
  releaseId: string;
  state: string;
}

export interface ToolIsolation {
  isolated: boolean;
  runner: string;
  detail: string;
  publicInvokeEnabled: boolean;
}

export interface ToolRegistry {
  tools: ToolDefinition[];
  isolation: ToolIsolation;
}

export type TokenScope = 'read' | 'draft';
export interface WorkspaceApiToken {
  tokenId: string; name: string; prefix: string; scopes: TokenScope[];
  createdAt: number; expiresAt: number; lastUsedAt: number | null; lastUsedClient: string | null;
  revokedAt: number | null; createdBy: string;
}
export interface ApiTokenCreated { item: WorkspaceApiToken; secret: string }
