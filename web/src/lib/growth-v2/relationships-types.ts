/**
 * Shapes of the relationship follow-up routes (`/api/workspaces/{w}/relationships`, source of truth
 * src/postriff_phase2/relationships/service.py). Fields the UI does not read are left out.
 */

export const RELATIONSHIP_STATES = ['new', 'replied', 'waiting', 'follow_up_due', 'won', 'closed'] as const;
export type RelationshipState = (typeof RELATIONSHIP_STATES)[number];
export type OpenRelationshipState = Exclude<RelationshipState, 'won' | 'closed'>;

export interface RelationshipOwner {
  userId: string;
  displayName: string;
  /** False when the person is no longer an active member: shown as a former owner, never re-assignable. */
  active: boolean;
}

export interface RelationshipDue {
  /** UTC instant (epoch seconds). */
  at: number;
  utc: string;
  /** Wall time in `timeZone`, `YYYY-MM-DDTHH:MM`. */
  local: string;
  timeZone: string;
  /** 1 = the second occurrence of a repeated local time (clocks going back). */
  fold: 0 | 1;
  offset: string;
  /** Moves on only when the due time itself changes; reminders are keyed on it. */
  revision: number;
}

export type FollowUpStatus = 'none' | 'scheduled' | 'due' | 'snoozed' | 'dismissed' | 'inactive';

export interface FollowUpView {
  status: FollowUpStatus;
  dueNow: boolean;
  until?: number;
  since?: number;
}

export interface ReplyRoute {
  /** `direct` only for an Inbox reply adapter with a Direct reply level (Threads); everything else is assisted. */
  kind: 'direct' | 'assisted';
  provider: string | null;
  approval?: 'exact';
  href?: string | null;
  reason?: 'not_direct' | 'unsupported_provider' | 'source_removed' | 'no_thread';
}

export interface RelationshipThread {
  threadId: string;
  provider: string;
  connectionId: string;
  author: string;
  excerpt: string;
  at: number | null;
  permalink: string | null;
  tombstoned: boolean;
  linkedAt: number | null;
  replyLevel: string;
  lastReply: { status: string; excerpt: string; at: number | null } | null;
  lastSentAt: number | null;
  replyRoute: ReplyRoute;
}

export interface RelationshipNote {
  id: string;
  text: string;
  by: string;
  at: number;
}

export interface RelationshipSuggestion {
  state: OpenRelationshipState;
  reason: 'reply_sent' | 'new_message' | 'due_passed';
  evidence: { threadId?: string; at?: number; dueAt?: number };
  key: string;
}

export interface RelationshipHistoryItem {
  kind: string;
  from: RelationshipState | null;
  to: RelationshipState | null;
  actor: string | null;
  meta: Record<string, unknown>;
  at: number;
}

export interface RelationshipContact {
  provider: string;
  accountId: string | null;
  ref: string | null;
}

export interface Relationship {
  id: string;
  revision: number;
  displayName: string;
  contact: RelationshipContact | null;
  interest: string | null;
  state: RelationshipState;
  previousState: OpenRelationshipState | null;
  stateChangedAt: number | null;
  owner: RelationshipOwner | null;
  nextAction: string | null;
  due: RelationshipDue | null;
  snoozedUntil: number | null;
  followUp: FollowUpView;
  won: { resultId: string; provenance: 'provider_native' | 'first_party_reported' | 'user_declared' | null } | null;
  threadIds: string[];
  noteCount: number;
  createdAt: number;
  updatedAt: number;
  createdBy: string;
}

export interface RelationshipDetail extends Relationship {
  notes: RelationshipNote[];
  threads: RelationshipThread[];
  suggestion: RelationshipSuggestion | null;
  history: RelationshipHistoryItem[];
  replyRoute: ReplyRoute;
}

export interface RelationshipList {
  relationships: Relationship[];
  nextCursor: string | null;
  counts: { open: number; dueNow: number };
  asOf: number;
  dataState: 'available' | 'partial' | 'unavailable' | 'stale';
  limits: { page: number; notes: number; threads: number };
}

export interface RelationshipWrite {
  relationship: RelationshipDetail;
  asOf: number;
  changed?: boolean;
  replayed?: boolean;
}

export interface RelationshipFilters {
  state?: 'open' | 'all' | RelationshipState;
  due?: 'due_now' | 'overdue' | 'upcoming' | 'any' | 'none';
  owner?: string;
  thread?: string;
  cursor?: string;
  limit?: number;
}

/** A due time as the person chose it: a wall time in a zone (fold only for a repeated hour), or null to clear it. */
export interface DueInput {
  local: string;
  timeZone: string;
  fold?: 0 | 1;
}

export interface RelationshipCreateInput {
  idempotencyKey: string;
  displayName?: string;
  threadId?: string;
  interest?: string;
  nextAction?: string;
  due?: DueInput | null;
  ownerId?: string | null;
}

export interface RelationshipEditInput {
  displayName?: string;
  interest?: string | null;
  nextAction?: string | null;
  due?: DueInput | null;
}

/** "What needs my attention" context the server adds to a `relationship.follow_up_due` item. */
export interface FollowUpAttentionContext {
  relationshipId: string;
  revision: number;
  displayName: string;
  state: RelationshipState;
  nextAction: string | null;
  interest: string | null;
  due: RelationshipDue | null;
  reason: 'due';
  owner: RelationshipOwner | null;
  threadId: string | null;
  exchange: { direction: 'inbound' | 'outbound'; author?: string; provider?: string; status?: string; excerpt: string; at: number | null }[];
  replyRoute: ReplyRoute;
}
