/**
 * Every sentence the Usage & plan page shows, in one place so it can be translated later
 * (the page is English-only for now). Dates go through `lib/time` (the person's locale and
 * zone), prices through `cents()`. Copy is written for any audience and claims only what the
 * API returns or the backend enforces.
 */
import type { InfobarContent } from '@/components/ui/infobar';
import { formatDate } from '@/lib/time';
import { humanize, type LifecycleAlert, type PlanTimeline } from './billing-model';

export const PAGE = {
  title: 'Usage & plan',
  description: 'What you have, what you have used, and what changes next.'
};

export const infoContent: InfobarContent = {
  title: 'How billing works',
  sections: [
    {
      title: 'Allowances stop, they never overcharge',
      description:
        'When a writing or media allowance runs out, paid drafting stops and tells you. Nothing is charged silently and there is no automatic overage.'
    },
    {
      title: 'Trial',
      description:
        'A trial comes with a one-time allowance and needs no card. Nothing converts automatically; when it ends, you choose a plan yourself.'
    },
    {
      title: 'Cancelling',
      description: 'Your drafts stay readable and exportable after a cancellation.'
    },
    {
      title: 'What counts as a writing batch',
      description:
        'A batch is one paid drafting run. Runs that use no paid model show at $0 and do not use a batch. Each run reserves an estimate first, then settles to the real cost, or is released if it failed.',
      links: [{ title: 'Usage & billing guide', url: '/docs/usage-and-billing' }]
    }
  ]
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export const LIFECYCLE_LABELS: Record<string, string> = {
  trial: 'Trial',
  active: 'Active',
  past_due: 'Payment failed',
  grace: 'Grace period',
  cancelled: 'Cancelled',
  expired: 'Expired'
};

export function lifecycleLabel(status: string | null | undefined) {
  if (!status) return 'Status unavailable';
  return LIFECYCLE_LABELS[status] ?? humanize(status);
}

export function timelineText(timeline: PlanTimeline): string {
  switch (timeline.kind) {
    case 'trial_left':
      return `${plural(timeline.daysLeft, 'day')} left · ends ${formatDate(timeline.endsAt)}`;
    case 'trial_ended':
      return `Trial ended ${formatDate(timeline.endedAt)}`;
    case 'renews':
      return `Renews ${formatDate(timeline.at)}`;
    case 'ends':
      return `Ends ${formatDate(timeline.at)}`;
    case 'grace':
      return timeline.until ? `Payment failed · grace period ends ${formatDate(timeline.until)}` : 'Payment failed · grace period end unavailable';
    case 'ended':
      return timeline.at ? `Ended ${formatDate(timeline.at)}` : 'Subscription ended';
    case 'unavailable':
      return timeline.what === 'trial_end' ? 'End date unavailable' : 'Renewal date unavailable';
  }
}

/**
 * The line under the Allowances title: when writing batches and media credits come back.
 * Allowances refill only when the payment provider reports an active subscription for a plan
 * (billing.py `_reconcile_entitlement`), so only a subscription that renews gets a reset date.
 * A trial, a subscription set to end, one that has ended and a failed payment all say "No reset".
 */
export function resetText(timeline: PlanTimeline, resetsAt: number | null): string {
  switch (timeline.kind) {
    case 'trial_left':
      return `No reset during the trial · ends ${formatDate(timeline.endsAt)}`;
    case 'trial_ended':
      return `No reset during the trial · ended ${formatDate(timeline.endedAt)}`;
    case 'ends':
      return `No reset · the subscription ends ${formatDate(timeline.at)}`;
    case 'ended':
      return timeline.at ? `No reset · the subscription ended ${formatDate(timeline.at)}` : 'No reset · the subscription has ended';
    case 'grace':
      return 'No reset until the payment is fixed';
    case 'unavailable':
      return timeline.what === 'trial_end' ? 'No reset during the trial · end date unavailable' : 'Reset date unavailable';
    case 'renews':
      return resetsAt ? `Resets ${formatDate(resetsAt)}` : 'Reset date unavailable';
  }
}

export function alertCopy(alert: LifecycleAlert): { title: string; description: string } {
  switch (alert.kind) {
    case 'payment_failed':
      return {
        title: 'Payment failed',
        description: alert.graceUntil
          ? `The grace period ends ${formatDate(alert.graceUntil)}. Update the payment method in the billing portal before then.`
          : 'The grace period end is unavailable. Update the payment method in the billing portal.'
      };
    case 'ended':
      return {
        title: 'Subscription ended',
        description: `${alert.at ? `It ended ${formatDate(alert.at)}. ` : ''}Drafts stay readable and exportable.`
      };
    case 'trial_ended':
      return {
        title: `Trial ended on ${formatDate(alert.at)}`,
        description: 'Publishing is paused. Drafts remain readable and exportable; choose a plan to resume publishing.'
      };
    case 'ending':
      return {
        title: `Your subscription ends ${formatDate(alert.at)}`,
        description: 'It will not renew. Changes to it are made in the billing portal.'
      };
  }
}

/** Plans subtitle from the mounted provider, not from the API's fixed `note`. */
export function providerNote(provider: string | undefined): string | null {
  if (provider === 'disabled') return 'Checkout is not enabled on this deployment yet.';
  if (provider === 'stripe') return 'Checkout and invoices are handled by Stripe. Nothing is charged until you confirm there.';
  return null;
}

export function budgetStatusLabel(status: string): string {
  if (status === 'candidate') return 'Provisional ceiling';
  if (status === 'approved') return 'Approved ceiling';
  return humanize(status);
}

/** The allowances a plan card lists, in reading order. */
export const PLAN_ALLOWANCES: readonly { key: string; label: string; unit?: string }[] = [
  { key: 'writingBatches', label: 'AI writing batches' },
  { key: 'mediaCredits', label: 'Media credits' },
  { key: 'connectedAccounts', label: 'Connected accounts' },
  { key: 'members', label: 'Members' },
  { key: 'storageMb', label: 'Storage', unit: 'MB' }
];

export const PRICE_STATUS: Record<string, string> = {
  proposed: 'Proposed price',
  retired: 'Retired'
};

export const CONFIRM = {
  loading: 'Waiting for the payment provider to confirm',
  loadingHint: 'This page checks again on its own, less often as time passes.',
  success: 'Subscription confirmed',
  successHint: 'Your plan and allowances below are updated.',
  timeout: 'Still waiting for the payment provider',
  timeoutHint: 'Refresh in a minute; nothing else is needed from you.',
  cancelled: 'Checkout cancelled. Nothing was charged.'
};

export const LEDGER_FILTER_LABELS = { all: 'All', writing: 'Writing', media: 'Media', other: 'Other' } as const;
