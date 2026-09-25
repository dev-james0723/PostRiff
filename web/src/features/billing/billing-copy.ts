/**
 * Every sentence the Usage & plan page shows, in one place so it can be translated later
 * (the page is English-only for now). Dates go through `lib/time` (the person's locale and
 * zone), prices through `cents()`. Copy is written for any audience and claims only what the
 * API returns or the backend enforces.
 */
import type { InfobarContent } from '@/components/ui/infobar';
import { formatDate } from '@/lib/time';
import { humanize, type PlanTimeline } from './billing-model';

export const PAGE = {
  title: 'Usage & plan'
};

export const infoContent: InfobarContent = {
  title: 'Billing',
  sections: [
    {
      title: 'No overage charges',
      description: 'When an allowance runs out, drafting pauses. You are never charged for going over.'
    },
    {
      title: 'Trial',
      description: 'No card needed. When it ends, you choose whether to subscribe.'
    },
    {
      title: 'Cancelling',
      description: 'Your drafts stay available to read and export.'
    },
    {
      title: 'Writing batches',
      description: 'One batch is one paid drafting run. Free runs show at $0 and use no batch.',
      links: [{ title: 'Usage & billing guide', url: '/docs/usage-and-billing' }]
    }
  ]
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export const LIFECYCLE_LABELS: Record<string, string> = {
  trial: 'Trial',
  active: 'Active',
  past_due: 'Payment failed',
  grace: 'Payment failed',
  cancelled: 'Cancelled',
  expired: 'Expired'
};

export function lifecycleLabel(status: string | null | undefined) {
  if (!status) return 'Status unavailable';
  return LIFECYCLE_LABELS[status] ?? humanize(status);
}

/** The one action the plan summary offers: the billing portal, the plan list, or nothing at all. */
export type PlanAction = 'portal' | 'plans' | null;

export interface PlanSummary {
  /** The plan's name, the page's first fact ("Trial", "Studio"). */
  title: string;
  /** A badge only when the state is not the plan's normal one (payment failed, cancelled, expired). */
  badge: string | null;
  /** The one line that says what happens next ("10 days left", "Renews Oct 3, 2026"). */
  line: string;
  /** The exact date behind a relative line, for the details disclosure; null when the line already has it. */
  exactDate: string | null;
  action: PlanAction;
  /** Label for the action button. */
  actionLabel: string | null;
  /** True when the person has to act (payment failed): the line is announced as an alert. */
  urgent: boolean;
}

/**
 * Usage & plan in one glance (UI simplification spec §9, §41): the plan, the next thing that
 * changes, and one action when there is one. When no action is possible the button is left out
 * rather than explained. Deliberately absent: "nothing converts automatically", export commentary
 * and anything about how billing is set up behind the scenes.
 */
export function planSummary(
  input: {
    timeline: PlanTimeline;
    planLabel: string | null | undefined;
    trial: boolean;
    status: string | null | undefined;
    isOwner: boolean;
    portalAvailable: boolean;
    checkoutAvailable: boolean;
  }
): PlanSummary {
  const { timeline, trial, status, isOwner } = input;
  const portal = isOwner && input.portalAvailable;
  const plans = isOwner && input.checkoutAvailable;
  const title = trial ? 'Trial' : input.planLabel || 'Plan unavailable';
  const unusual = status && status !== 'active' && status !== 'trial' ? lifecycleLabel(status) : null;
  const base = { title, badge: trial ? null : unusual, exactDate: null, urgent: false };
  const manage = portal ? ({ action: 'portal', actionLabel: 'Manage plan' } as const) : ({ action: null, actionLabel: null } as const);
  const choose = plans ? ({ action: 'plans', actionLabel: 'Choose a plan' } as const) : ({ action: null, actionLabel: null } as const);

  switch (timeline.kind) {
    case 'trial_left':
      return { ...base, line: `${plural(timeline.daysLeft, 'day')} left`, exactDate: `Ends ${formatDate(timeline.endsAt)}`, ...(portal ? manage : choose) };
    case 'trial_ended':
      return { ...base, badge: 'Ended', line: 'Publishing is paused', exactDate: `Ended ${formatDate(timeline.endedAt)}`, ...choose };
    case 'renews':
      return { ...base, line: `Renews ${formatDate(timeline.at)}`, ...manage };
    case 'ends':
      return { ...base, line: `Ends ${formatDate(timeline.at)} · won’t renew`, ...manage };
    case 'grace':
      return {
        ...base,
        badge: 'Payment failed',
        line: timeline.until ? `Update payment by ${formatDate(timeline.until)}` : 'Update your payment method',
        urgent: true,
        ...(portal ? { action: 'portal', actionLabel: 'Update payment' } : { action: null, actionLabel: null })
      };
    case 'ended':
      return { ...base, line: timeline.at ? `Ended ${formatDate(timeline.at)}` : 'Ended', ...choose };
    case 'unavailable':
      return { ...base, line: '', ...(portal || !trial ? manage : choose) };
  }
}

/**
 * The line under the Usage heading: when writing batches and media credits come back. Only a
 * subscription that renews refills them (billing.py `_reconcile_entitlement`), so every other
 * state says nothing here; the plan summary already carries its date.
 */
export function resetText(timeline: PlanTimeline, resetsAt: number | null): string | null {
  if (timeline.kind !== 'renews' || !resetsAt) return null;
  return `Resets ${formatDate(resetsAt)}`;
}

/** Plans subtitle, only where it tells the person something about paying. */
export function checkoutNote(provider: string | undefined): string | null {
  if (provider === 'stripe') return 'Checkout by Stripe. Nothing is charged until you confirm.';
  return null;
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
  loading: 'Confirming payment…',
  success: 'Subscription confirmed',
  timeout: 'Still confirming payment',
  timeoutHint: 'Refresh in a minute.',
  cancelled: 'Checkout cancelled. Nothing was charged.'
};

export const LEDGER_FILTER_LABELS = { all: 'All', writing: 'Writing', media: 'Media', other: 'Other' } as const;
