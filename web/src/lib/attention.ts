import type { ChannelView, ProviderView, Snapshot, Usage } from '@/lib/api/types';
import { attentionSentence, expiringSoon, isConnected, needsAttention, sortForAttention } from '@/lib/channels/state';
import { daysUntil, relativeTime } from '@/lib/time';

/**
 * Everything the "Needs your attention" card lists, derived from real query results only.
 * A source that could not be read adds nothing: an unread workspace is not "no voice", and an
 * unread channel list is not "no channels". The caller shows `unavailable` as its own warning.
 *
 * Shared by Home, Overview and the sidebar badge.
 */

export interface AttentionItem {
  /** Stable across count changes, so an entry updates in place instead of leaving and re-entering. */
  id: string;
  tone: 'warning' | 'info';
  title: string;
  description: string;
  href: string;
  action: string;
}

/** The slice of a query result this needs; TanStack's `UseQueryResult` fits. */
interface Source<T> {
  data?: T;
  isError: boolean;
}

export type AttentionSource = 'workspace' | 'channels' | 'plan';

export interface AttentionInput {
  snapshot: Source<Snapshot>;
  channels: Source<{ channels: ChannelView[]; providers: ProviderView[] }>;
  usage: Source<Usage>;
  /** Epoch seconds. */
  now: number;
}

export interface Attention {
  items: AttentionItem[];
  approvals: number;
  /** Sources that failed to load, so some reminders may be missing. */
  unavailable: AttentionSource[];
}

/** Snapshot channel states (`store.py: channel_state`) that ask for a person, used only when /channels is unreadable. */
const SNAPSHOT_RECONNECT = 'Reconnect';
const SNAPSHOT_FINISH = 'Finish setup';

export function deriveAttention({ snapshot, channels, usage, now }: AttentionInput): Attention {
  const items: AttentionItem[] = [];
  const unavailable: AttentionSource[] = [];
  const state = snapshot.isError ? undefined : snapshot.data?.state;
  const channelData = channels.isError ? undefined : channels.data;
  const usageData = usage.isError ? undefined : usage.data;
  if (snapshot.isError) unavailable.push('workspace');
  if (channels.isError) unavailable.push('channels');
  if (usage.isError) unavailable.push('plan');

  if (state?.speaker?.provisional && snapshot.data?.membership?.role === 'owner') {
    items.push({ id: 'voice-proposal', tone: 'info', title: 'Review your proposed voice', description: 'A proposed voice is waiting for your decision. Approving it sends existing drafts back for review.', href: '/app/workspace/brand', action: 'Review' });
  } else if (state && !state.speaker?.activeRevision) {
    items.push({
      id: 'voice',
      tone: 'info',
      title: 'Set up your voice',
      description: 'Two minutes: what you are building, who it is for, and a tone. You can review and schedule drafts now; a voice profile guides future drafts.',
      href: '/app/workspace/brand',
      action: 'Set up'
    });
  }

  if (usageData?.lifecycle?.status === 'past_due') {
    items.push({
      id: 'past-due',
      tone: 'warning',
      title: 'Payment failed',
      description: 'Publishing stays on during the grace period. Update your payment method to keep it that way.',
      href: '/app/account/billing',
      action: 'Fix billing'
    });
  }

  if (channelData) {
    // Held jobs name their connection; they keep a channel in the list even when its state looks fine.
    const held: Record<string, number> = {};
    for (const job of state?.phase2?.jobs ?? []) {
      const channelId = job.manifest?.channelId;
      if (channelId && job.state === 'held') held[channelId] = (held[channelId] ?? 0) + 1;
    }
    for (const channel of sortForAttention(channelData.channels, now, held)) {
      const heldJobs = held[channel.id] ?? 0;
      if (!needsAttention(channel, now, heldJobs)) break;
      const sentence = attentionSentence(channel, now, heldJobs);
      if (!sentence) continue;
      const expiring = expiringSoon(channel, now) && heldJobs === 0;
      items.push({
        id: `${expiring ? 'expiring' : 'reconnect'}-${channel.id}`,
        tone: expiring ? 'info' : 'warning',
        title: expiring
          ? `${channel.platform} access ends ${relativeTime(channel.expiresAt, now)}`
          : `Reconnect ${channel.platform}`,
        description: `${channel.account}: ${sentence}`,
        href: '/app/channels?filter=attention',
        action: 'Open channels'
      });
    }
  } else if (state) {
    // Fallback while /channels cannot be read: the snapshot's own coarse state for each account.
    for (const channel of state.phase2?.channels ?? []) {
      if (channel.displayState !== SNAPSHOT_RECONNECT && channel.displayState !== SNAPSHOT_FINISH) continue;
      const reconnect = channel.displayState === SNAPSHOT_RECONNECT;
      items.push({
        id: `reconnect-${channel.id}`,
        tone: reconnect ? 'warning' : 'info',
        title: reconnect ? `Reconnect ${channel.platform}` : `Finish setting up ${channel.platform}`,
        description: reconnect
          ? `${channel.account}: access has expired or was revoked. Scheduled posts for this account are waiting.`
          : `${channel.account}: the account still needs to be verified before it can publish.`,
        href: '/app/channels',
        action: 'Open channels'
      });
    }
  }

  const needsReview = (state?.phase2?.reviews ?? []).filter((review) => review.status === 'needs_review').length;
  if (needsReview > 0) {
    items.push({
      id: 'approvals',
      tone: 'info',
      title: `${needsReview} draft${needsReview === 1 ? '' : 's'} waiting for approval`,
      description: 'Nothing publishes until you approve the exact text, media and time.',
      href: '/app/queue',
      action: 'Review now'
    });
  }

  const trialDays = (usageData?.lifecycle?.status === 'trial' || (usageData?.entitlement?.source === 'trial' && usageData?.lifecycle?.status === 'expired')) ? daysUntil(usageData.entitlement?.resetsAt, now) : null;
  if (trialDays !== null && trialDays <= 5) {
    items.push({
      id: 'trial',
      tone: 'info',
      title: trialDays > 0 ? `Trial ends in ${trialDays} day${trialDays === 1 ? '' : 's'}` : 'Trial has ended',
      description: 'Your drafts stay readable and exportable either way. Choose a plan to keep publishing.',
      href: '/app/account/billing',
      action: 'See plans'
    });
  }

  if (channelData) {
    const connected = channelData.channels.filter((channel) => isConnected(channel));
    const unreviewed = channelData.providers.filter(
      (provider) => !provider.productionReviewed && connected.some((channel) => channel.platform === provider.platform)
    );
    if (unreviewed.length) {
      items.push({
        id: 'export-only',
        tone: 'info',
        title: `${unreviewed.map((provider) => provider.platform).join(', ')}: publish is export-only for now`,
        description: 'Provider review is in progress. Until it passes, PostRiff prepares each post and you complete the final step.',
        href: '/app/channels',
        action: 'Details'
      });
    }
    if (channelData.channels.length === 0) {
      items.push({
        id: 'first-channel',
        tone: 'info',
        title: 'Connect your first channel',
        description: 'Drafts can be written and exported now; connecting an account lets you schedule and publish.',
        href: '/app/channels',
        action: 'Connect'
      });
    }
  }

  return { items, unavailable, approvals: needsReview };
}
