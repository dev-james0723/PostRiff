import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import type { Audience, Capability, ChannelView, ProviderView, Thread } from '@/lib/api/types';
import { LEVEL_MEANING } from '@/lib/channels/capabilities';

/**
 * Pure helpers for the Inbox. The audience API (`GET /audience/threads`) returns threads, the
 * comments level per connection and a limits sentence. Reply history, provider timestamps,
 * permalinks and counts are not in that response yet, so each is read as an optional field:
 * when the server starts sending one, the page uses it; until then the page says it is unknown.
 */

export type InboxFilter = 'all' | 'unanswered' | 'replied';
export const INBOX_FILTERS: readonly InboxFilter[] = ['all', 'unanswered', 'replied'];

import type { ReplyRecord } from '@/lib/api/types';
export type { ReplyRecord } from '@/lib/api/types';

/** A saved reply draft as `POST …/reply-drafts` returned it. */
export interface SavedDraft {
  draftId: string;
  text: string;
  origin: string;
  label: string;
}

/** What `POST …/reply-preview` returned; the dialog shows `manifest.text`, the text that gets approved. */
export interface ReplyPreview {
  draftId: string;
  manifest: Record<string, unknown>;
  digest: string;
  action: string;
  replyLevel: string;
}

/** Approved and later states: a reply was approved and not cancelled or held back. */
const ANSWERED = new Set(['approved', 'submitting', 'submitted', 'verified', 'uncertain']);

export function isAnswered(reply: Pick<ReplyRecord, 'status'>) {
  return ANSWERED.has(reply.status);
}

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** Reply history from the API, or null when the server did not report it for this thread. */
export function apiReplies(thread: Thread): ReplyRecord[] | null {
  return Array.isArray(thread.replies) ? thread.replies : null;
}

/** True once the server reports reply history for the threads it returns. */
export function replyHistoryReported(threads: Thread[]) {
  return threads.length > 0 && threads.every((thread) => apiReplies(thread) !== null);
}

/** API replies first; a reply approved in this visit fills in only where the API has not caught up. */
export function mergedReplies(thread: Thread, session: ReplyRecord[] | undefined): ReplyRecord[] {
  const fromApi = apiReplies(thread) ?? [];
  const known = new Set(fromApi.map((reply) => reply.draftId));
  return [...fromApi, ...(session ?? []).filter((reply) => !known.has(reply.draftId))];
}

/** A link to the comment on the provider, only when the server sent a web address. */
export function threadPermalink(thread: Thread): string | null {
  const value = asString(thread.permalink);
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : null;
  } catch {
    return null;
  }
}

/** The provider's own comment time when the server sends it; otherwise when PostRiff first saw it. */
export function threadTime(thread: Thread): { at: number; firstSeen: boolean } {
  const provider = thread.createdAtProvider;
  return typeof provider === 'number' ? { at: provider, firstSeen: false } : { at: thread.ingestedAt, firstSeen: true };
}

/** Counts the server computed over every comment, when it sends them. */
export function apiCounts(data: Audience): Partial<Record<InboxFilter, number>> | null {
  const raw = data.counts;
  if (!raw || typeof raw !== 'object') return null;
  const counts = raw as Record<string, unknown>;
  const pick = (key: string) => (typeof counts[key] === 'number' ? (counts[key] as number) : undefined);
  return { all: pick('all'), unanswered: pick('unanswered'), replied: pick('replied') };
}

/** The API's limit on how many comments one response carries (`audience.py` threads: LIMIT 200). */
export const THREAD_PAGE_LIMIT = 200;

export function providerName(provider: string, channel?: Pick<ChannelView, 'platform'> | null) {
  if (channel?.platform) return channel.platform;
  return provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : 'the provider';
}

export function authorLabel(author: string) {
  return author ? `@${author.replace(/^@/, '')}` : 'Unknown account';
}

/** A reply's backend status in plain words. Approved replies are not sent yet: nothing picks them up. */
export function replyStatusView(status: string): { label: string; badge: AnimatedBadgeStatus } {
  switch (status) {
    case 'draft':
      return { label: 'Draft', badge: 'neutral' };
    case 'approved':
      return { label: 'Approved · reconfirm when sending is enabled', badge: 'info' };
    case 'submitting':
      return { label: 'Sending', badge: 'loading' };
    case 'submitted':
      return { label: 'Sent · waiting for the provider to confirm', badge: 'info' };
    case 'verified':
      return { label: 'Posted', badge: 'success' };
    case 'uncertain':
      return { label: 'Outcome unclear · not resent', badge: 'warning' };
    case 'held':
    case 'failed':
      return { label: 'Held · not sent', badge: 'danger' };
    case 'cancelled':
      return { label: 'Cancelled', badge: 'neutral' };
    default:
      return { label: status.replace(/_/g, ' '), badge: 'neutral' };
  }
}

/** Short status for a list row. */
export function replyStatusShort(status: string) {
  if (status === 'approved') return 'Approved';
  return replyStatusView(status).label.split(' · ')[0];
}

/**
 * Says what wrote a draft. `ai_fixture` is a fixed starter sentence with no model behind it
 * (`audience.py` draft_reply), so it is never called AI here, whatever label the API sends.
 */
export function originLabel(origin: string | undefined, apiLabel?: string) {
  if (origin === 'manual') return 'Your reply';
  if (origin === 'ai_fixture') return 'Starter line (not written by AI)';
  if (modelWrote(origin)) return apiLabel || 'AI suggestion';
  return apiLabel || 'Reply';
}

/** True when the draft's origin says a language model wrote it (for example a future `ai_model`). */
export function modelWrote(origin: string | undefined) {
  if (!origin || origin === 'ai_fixture') return false;
  return origin.startsWith('ai_') || /model/i.test(origin);
}

/** One capability's evidence for the hover card; an empty evidence string is said as such, never invented. */
export function evidenceSentence(capability: Capability | undefined, providerOffers: boolean | undefined, platform: string) {
  const evidence = capability?.evidence?.trim();
  if (evidence) return evidence;
  const level = capability?.level ?? 'Unsupported';
  if (level !== 'Unsupported') return LEVEL_MEANING[level] ?? level;
  if (providerOffers === false) return `${platform} does not offer this to PostRiff.`;
  return 'Not verified for this account, so PostRiff treats it as unavailable.';
}

export function providerFor(platform: string, providers: ProviderView[] | undefined) {
  return providers?.find((provider) => provider.platform === platform) ?? null;
}

/** Capability evidence and implementation support are separate checks. */
export function commentsReadFor(platform: string, providers: ProviderView[] | undefined) {
  return providerFor(platform, providers)?.commentsReadImplemented === true;
}

export function commentReadNames(providers: ProviderView[] | undefined) {
  const names = providers?.filter((provider) => provider.commentsReadImplemented).map((provider) => provider.platform);
  return names?.length ? names.join(' and ') : 'supported';
}
