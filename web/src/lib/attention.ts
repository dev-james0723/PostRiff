import type { ChannelView, ProviderView, Snapshot, Usage } from '@/lib/api/types';
import { allowanceReminder, V2_CATALOG_VERSION, billingModeOf } from '@/lib/billing/mode';
import { billingCopy } from '@/lib/billing/mode-copy';
import { attentionSentence, expiringSoon, isConnected, needsAttention, sortForAttention } from '@/lib/channels/state';
import { daysUntil, formatNumber, relativeTime } from '@/lib/time';

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
    items.push({ id: 'voice-proposal', tone: 'info', title: 'Review your proposed voice', description: 'Approving it sends existing drafts back for review.', href: '/app/workspace/brand', action: 'Review' });
  } else if (state && !state.speaker?.activeRevision) {
    items.push({
      id: 'voice',
      tone: 'info',
      title: 'Set up your voice',
      description: 'About two minutes.',
      href: '/app/workspace/brand',
      action: 'Set up'
    });
  }

  if (usageData?.lifecycle?.status === 'past_due') {
    items.push({
      id: 'past-due',
      tone: 'warning',
      title: 'Payment failed',
      description: 'Update your payment method to keep publishing.',
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
          ? `${channel.account}: access expired. Posts are on hold.`
          : `${channel.account}: not verified yet.`,
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
      description: 'Nothing publishes until you approve.',
      href: '/app/queue',
      action: 'Review now'
    });
  }

  // Automations: runs whose drafts nobody has opened yet (the in-app "drafts ready" digest).
  const planning = state?.raffi?.campaignPlanning;
  const readyRuns = (planning?.occurrences ?? []).filter((run) => run.state === 'completed' && run.conversationId && !run.seenAt);
  if (readyRuns.length > 0) {
    const names = Array.from(new Set(readyRuns.map((run) => planning?.recurringTasks.find((task) => task.id === run.taskId)?.name).filter((name): name is string => Boolean(name))));
    const drafts = readyRuns.reduce((sum, run) => sum + (run.draftCount ?? 1), 0);
    items.push({
      id: 'automation-drafts',
      tone: 'info',
      title: `${drafts} automation draft${drafts === 1 ? '' : 's'} ready`,
      description: names.length ? `From ${names.slice(0, 2).join(', ')}${names.length > 2 ? ` and ${names.length - 2} more` : ''}.` : 'Nothing is scheduled until you approve.',
      href: '/app/automations',
      action: 'Review drafts'
    });
  }

  // A Free workspace (Pricing v2) has no trial to end, even when a trial it once had expired into Free.
  const freePreview = billingModeOf(usageData) === 'free_preview';
  const trialDays = !freePreview && (usageData?.lifecycle?.status === 'trial' || (usageData?.entitlement?.source === 'trial' && usageData?.lifecycle?.status === 'expired')) ? daysUntil(usageData?.entitlement?.resetsAt, now) : null;
  if (trialDays !== null && trialDays <= 5) {
    items.push({
      id: 'trial',
      tone: 'info',
      title: trialDays > 0 ? `Trial ends in ${trialDays} day${trialDays === 1 ? '' : 's'}` : 'Trial has ended',
      // Under Pricing v2 an ended trial continues on Free (drafts and publishing stay); only the legacy catalog stops.
      description: usageData?.catalogVersion === V2_CATALOG_VERSION
        ? 'When it ends, this workspace continues on Free and keeps your drafts. See what Creator adds.'
        : 'Choose a plan to keep publishing.',
      href: '/app/account/billing',
      action: 'See plans'
    });
  }

  // The writing allowance is no longer an Overview headline number (Time back took that place); running low or out
  // is actionable, so it is a reminder here. The full meters stay under Billing. Which allowance follows the
  // billing mode: legacy writing batches, Creator's managed credits, and nothing on Free (Pricing v2).
  const reminder = allowanceReminder(usageData, now);
  const credits = billingCopy('en').attention;
  if (reminder?.kind === 'batches') {
    const left = reminder.left;
    const resets = reminder.resetsAt ? ` It resets ${relativeTime(reminder.resetsAt, now)}.` : '';
    items.push({
      id: 'writing-allowance',
      tone: left === 0 ? 'warning' : 'info',
      title: left === 0 ? 'Writing allowance used up' : `${left} writing ${left === 1 ? 'batch' : 'batches'} left`,
      description: (left === 0 ? 'New drafts pause until more are available; nothing extra is charged.' : 'Drafting pauses when they run out; nothing extra is charged.') + resets,
      href: '/app/account/billing',
      action: 'See plan'
    });
  } else if (reminder) {
    const text =
      reminder.kind === 'credits_out'
        ? { tone: 'warning' as const, title: credits.creditsOutTitle, description: reminder.resetsAt ? credits.creditsOutBody(relativeTime(reminder.resetsAt, now)) : credits.creditsOutBodyNoDate }
        : reminder.kind === 'credits_low'
          ? { tone: 'info' as const, title: credits.creditsLowTitle(formatNumber(reminder.left)), description: credits.creditsLowBody }
          : { tone: 'warning' as const, title: credits.debtTitle, description: credits.debtBody(formatNumber(reminder.debt)) };
    items.push({ id: 'writing-allowance', ...text, href: '/app/account/billing', action: credits.action });
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
        title: `${unreviewed.map((provider) => provider.platform).join(', ')}: you post the last step`,
        description: 'Rafii prepares each post; you publish it.',
        href: '/app/channels',
        action: 'Details'
      });
    }
    if (channelData.channels.length === 0) {
      items.push({
        id: 'first-channel',
        tone: 'info',
        title: 'No accounts connected',
        description: 'Connect one to schedule and publish.',
        href: '/app/channels',
        action: 'Connect'
      });
    }
  }

  return { items, unavailable, approvals: needsReview };
}
