/**
 * Shapes of the Rafii coworker API (docs/design/site-agent/adaptive-social-coworker/API.md; source of truth
 * src/postriff_phase2/coworker/http.py, coworker/service.py, notifications/service.py). Fields the UI does not
 * read are left out or kept loose; nothing here is invented beyond what those routes return.
 */

/* ---------- status + flags ---------- */

export type CoworkerFlag =
  | 'RAFII_SKILL_REGISTRY_V2_ENABLED'
  | 'RAFII_NOTIFICATIONS_V2_ENABLED'
  | 'RAFII_WEB_PUSH_ENABLED'
  | 'RAFII_ADAPTIVE_SKILLS_ENABLED'
  | 'RAFII_WEEKLY_OPERATOR_ENABLED'
  | 'RAFII_RESEARCH_BROKER_ENABLED'
  | 'RAFII_CREATIVE_AGENT_ENABLED'
  | 'RAFII_PERFORMANCE_LEARNING_ENABLED'
  | 'RAFII_LISTENING_ENABLED'
  | 'RAFII_ENGAGEMENT_COPILOT_ENABLED'
  | 'RAFII_GROWTH_EXPERIMENTS_ENABLED';

export interface CoworkerStatus {
  flags: Partial<Record<CoworkerFlag, boolean>>;
  notifications: { enabled: boolean; push?: boolean; email?: boolean; catalogVersion?: string | number };
  weekly: { recipes: number; weeks: number };
}

/** Every mutation re-reads what it changed: `false` means it did not happen as asked. */
export interface Verified {
  verified: boolean;
}

/* ---------- "What needs my attention?" ---------- */

export interface AttentionItem {
  id: string;
  type: string;
  priority: number;
  urgent: boolean;
  title: string;
  why: string;
  detail: string;
  evidence: { entityType?: string | null; entityId?: string | null; platform?: string | null; account?: string | null; count?: number | null };
  href: string;
}

export interface AttentionResponse {
  items: AttentionItem[];
  counts: { total: number; urgent: number };
  rules: string;
}

/* ---------- notification centre + preferences + push ---------- */

export type DeliveryStatus = 'delivered' | 'read' | 'acted';

export interface ServerNotification {
  id: string;
  status: DeliveryStatus;
  createdAt: number;
  type: string;
  category: string;
  severity: string;
  entity: { type: string | null; id: string | null };
  payload: { title?: string; platform?: string; reason?: string; href?: string; count?: number; weekOf?: string; why?: string; [key: string]: unknown };
  workspaceId?: string | null;
  readAt: number | null;
  actedAt: number | null;
  actionable: boolean;
}

export interface NotificationCenter {
  items: ServerNotification[];
  unread: number;
  catalogVersion: string | number;
}

export interface MarkResult extends Verified {
  changed: boolean;
  status: string | null;
}

/** Every unread notification in this workspace marked read; `unread` is the server's recount (verified when 0). */
export interface MarkAllResult extends Verified {
  changed: number;
  unread: number;
}

export type EmailMode = 'immediate' | 'digest' | 'off';
export type PushMode = 'immediate' | 'off';
export type DigestFrequency = 'daily' | 'weekly' | 'off';

export interface PreferenceFields {
  in_app?: boolean | null;
  email_mode?: EmailMode | null;
  push_mode?: PushMode | null;
  digest_frequency?: DigestFrequency | null;
  quiet_start?: number | null;
  quiet_end?: number | null;
  time_zone?: string | null;
  muted_until?: number | null;
  email_unsubscribed?: boolean | null;
}

export interface CatalogEvent {
  category: string;
  severity: string;
  email: EmailMode;
  push: PushMode;
  transactional?: boolean;
}

export interface NotificationPreferences {
  catalog: { version: string | number; categories: string[]; events: Record<string, CatalogEvent> };
  rows: (PreferenceFields & { scope: string; category: string })[];
  effective: Record<string, PreferenceFields>;
  /** `devices` is a count here; the list is `GET push-subscriptions`. */
  push: { available: boolean; vapidPublicKey: string | null; devices: number };
  email: { available: boolean };
}

export type PreferencePatch = Omit<PreferenceFields, 'muted_until'> & {
  scope: 'workspace' | 'all';
  category: string;
  /** 1–720 hours, or null to unmute. */
  mute_hours?: number | null;
};

export interface PreferenceSaved extends Verified {
  scope: string;
  category: string;
  stored: PreferenceFields;
}

export interface PushDevice {
  id: string;
  label: string | null;
  createdAt: number;
  lastSuccessAt: number | null;
}

export interface PushSubscriptionBody {
  endpoint: string;
  expirationTime: number | null;
  keys: { p256dh: string; auth: string };
}

/* ---------- weekly social operator ---------- */

export type WeekState =
  | 'planned'
  | 'researching'
  | 'generating'
  | 'quality_check'
  | 'ready_for_review'
  | 'approved'
  | 'scheduled'
  | 'needs_input'
  | 'needs_source'
  | 'needs_asset'
  | 'channel_unavailable'
  | 'approval_expired';

export type SlotStatus =
  | 'planned'
  | 'needs_source'
  | 'needs_input'
  | 'needs_asset'
  | 'channel_unavailable'
  | 'drafted'
  | 'needs_revision'
  | 'ready'
  | 'accepted'
  | 'in_queue'
  | 'approved'
  | 'scheduled'
  | 'published'
  | 'failed'
  | 'rejected'
  | 'approval_expired';

export interface RecipeDestination {
  channelId: string;
  platform?: string;
  account?: string;
  language: string;
  postsPerWeek: number;
}

export interface Recipe {
  id: string;
  name: string;
  goals: string[];
  destinations: RecipeDestination[];
  contentMix: Record<string, number>;
  campaignIds?: string[];
  sourceIds?: string[];
  planningDay: number;
  planningHour: number;
  timeZone: string;
  voiceMode: 'personalized' | 'neutral';
  reviewPolicy?: string;
  expectImages: boolean;
  useResearch: boolean;
  maxCostUsdMicroPerWeek: number;
  model?: string | null;
  status: 'active' | 'paused' | 'deleted';
  version: number;
  createdAt?: number;
  updatedAt?: number;
}

export interface RecipeInput {
  name: string;
  goals: string[];
  destinations: { channelId: string; postsPerWeek: number; language: string }[];
  contentMix: Record<string, number>;
  planningDay: number;
  planningHour: number;
  timeZone: string;
  voiceMode: 'personalized' | 'neutral';
  expectImages: boolean;
  useResearch: boolean;
  maxCostUsdMicroPerWeek: number;
  /** The writing model for this recipe's drafts; omitted = the workspace default. */
  model?: string | null;
}

export interface Finding {
  code: string;
  detail?: string;
  examples?: string[];
}

export interface SlotQuality {
  evaluator?: string;
  patterns?: string;
  meaning?: Finding[];
  meaningBasis?: 'approved_facts' | 'your_answer' | 'none' | null;
  style?: Finding[];
  lint?: Finding[];
  voiceFit?: { checked?: number; differs?: { trait?: string; evidence?: string }[]; unavailable?: string } | null;
}

export interface CreativePlan {
  plans?: {
    platform?: string;
    format?: string;
    ratio?: string;
    size?: string;
    sourceType?: string;
    sourceWhy?: string;
    message?: string | null;
    altText?: { draft?: string | null } | null;
    note?: string;
  }[];
  missingAssets?: { need?: string; why?: string }[];
  compiled?: unknown;
}

export interface Slot {
  id: string;
  day: string;
  localTime: string;
  timeZone?: string;
  platform: string;
  account?: string | null;
  language: string;
  channelId?: string;
  contentType: string;
  goal: string;
  angle: string;
  sourceIds?: string[];
  status: SlotStatus;
  reason: string | null;
  question: string | null;
  answer?: string | null;
  variantId: string | null;
  quality: SlotQuality | null;
  creative: CreativePlan | null;
  draft?: { text?: string | null; unknowns?: unknown; needsReview?: unknown } | null;
}

export interface WeekHistoryEntry {
  at: number;
  state: string;
  note: string;
}

export interface Week {
  id: string;
  recipeId: string;
  weekOf: string;
  isoWeek?: string;
  state: WeekState;
  blockedReason: string | null;
  slots: Slot[];
  history?: WeekHistoryEntry[];
  readyAt?: number | null;
  counts?: Partial<Record<SlotStatus, number>>;
}

export interface WeeklyList {
  recipes: Recipe[];
  weeks: Week[];
}

export interface WeekDetail {
  week: Week;
  counts: Partial<Record<SlotStatus, number>>;
  queueHref: string;
}

export interface PrepareResult extends Verified {
  week: Week;
  advanced: boolean;
  drafted?: number;
}

export type SlotAction = 'accept' | 'reject' | 'answer' | 'redo' | 'skip';

export interface SlotActionResult extends Verified {
  week: Week;
  slot: Slot;
  next: string | null;
}

/* ---------- personalization (adaptive overlays) ---------- */

export interface OverlayScope {
  platform?: string;
  language?: string;
  contentTypeId?: string;
  audience?: string;
}

export interface OverlayItem {
  id: string;
  memoryType: 'voice' | 'brand';
  origin: 'explicit' | 'inferred';
  statement: string;
  scope: OverlayScope;
  status: 'active' | 'disabled' | 'paused' | 'retired' | 'expired';
  confidence: number;
  evidenceIds?: string[];
  counterEvidenceIds?: string[];
  lastSupportedAt?: number | null;
  expiresAt?: number | null;
  kind: 'note' | 'learned';
  source?: string | null;
  updatedAt?: number;
  createdAt?: number;
  since?: number | null;
}

export interface StrategyHypothesis {
  id: string;
  platform: string;
  dimension: string;
  statement: string;
  confidence: 'low' | 'moderate' | 'high' | string;
  status: string;
  /** `[a, b]` from overlays; `{a, b}` from performance. */
  samples: [number, number] | { a: number; b: number };
  effect?: number | null;
  evidenceIds?: string[];
  counterEvidenceIds?: string[];
  causal: false | boolean;
  dateRange?: [number | null, number | null];
  expiresAt: number | null;
  why?: string;
  memoryType?: 'strategy';
}

export interface OverlaysView {
  voice: OverlayItem[];
  brand: OverlayItem[];
  strategy: StrategyHypothesis[];
  revisions?: unknown;
  history?: { at: number; id?: string; change: string; count?: number }[];
}

export interface NoteInput {
  memoryType: 'voice' | 'brand';
  statement: string;
  scope: OverlayScope;
}

export interface PerformanceView {
  posts: number;
  measured: number;
  unavailable: number;
  hypotheses: StrategyHypothesis[];
  rules: { minimumPerGroup: number; minimumDifference: string; causal: false; note: string };
}

/* ---------- listening + engagement ---------- */

export interface Opportunity {
  id: string;
  title: string;
  url?: string;
  evidence: { url?: string; snippet?: string; provenance?: unknown }[];
  relevance: number;
  novelty: number;
  freshness: number;
  score: number;
  confidence: 'low' | 'moderate' | 'high' | string;
  status: 'open' | 'acted' | 'dismissed';
  expiresAt: number;
  createdAt?: number;
  ageDays?: number;
  why: string;
  proposedAction: string;
}

export interface Watchlist {
  id: string;
  query: string;
  goal: string;
  active: boolean;
  lastRunAt: number | null;
}

export interface ListeningView {
  watchlists: Watchlist[];
  opportunities: Opportunity[];
  coverage: string;
  now: number;
}

export interface EngagementSummary {
  items: { threadId: string; author?: string; provider?: string; category: string; priority: string; fresh?: boolean; ageHours: number; why: string; summary: string; replyAvailable?: boolean }[];
  counts: Partial<Record<'needs_reply' | 'review' | 'fyi' | 'done' | 'ignore', number>>;
  note: string;
  replySendingEnabled?: boolean;
}
