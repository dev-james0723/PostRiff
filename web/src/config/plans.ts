/**
 * Public plan catalogue. Mirrors `migrations/postriff/007_consumer_web_billing.sql`
 * (pr_plan_terms) and stays the single source for prices on the site.
 *
 * `status` follows decision D3: 'proposed' until the commercial decision flips
 * the database row to 'active' (see docs/postriff-consumer-web/billing-and-email.md).
 * Nothing here charges anyone; checkout is gated by the API on the live status.
 */
export type PlanId = 'studio' | 'assist';
export type PlanStatus = 'proposed' | 'active';

export interface Plan {
  id: PlanId;
  planTermsId: string;
  name: string;
  tagline: string;
  priceCents: number;
  currency: 'USD';
  interval: 'month';
  status: PlanStatus;
  highlights: string[];
  limits: {
    connectedAccounts: number;
    writingBatches: number | 'none';
    mediaCredits: number;
    storageMb: number;
    members: number;
  };
}

export const plans: Plan[] = [
  {
    id: 'studio',
    planTermsId: 'studio-v1',
    name: 'Studio',
    tagline: 'Draft, approve and publish in your own words.',
    priceCents: 1900,
    currency: 'USD',
    interval: 'month',
    status: 'proposed',
    highlights: [
      '3 connected accounts',
      'Manual drafting, approvals and scheduling',
      '1 GB media storage',
      'Calendar, queue and publishing receipts',
      'Export everything, any time'
    ],
    limits: { connectedAccounts: 3, writingBatches: 'none', mediaCredits: 0, storageMb: 1000, members: 1 }
  },
  {
    id: 'assist',
    planTermsId: 'assist-v1',
    name: 'Studio Assist',
    tagline: 'Everything in Studio, plus AI writing in your voice.',
    priceCents: 3900,
    currency: 'USD',
    interval: 'month',
    status: 'proposed',
    highlights: [
      '3 connected accounts',
      '100 AI writing batches per month',
      'Per-platform rewrites from one source',
      '1 GB media storage',
      'Usage stops at the limit — never a surprise charge'
    ],
    limits: { connectedAccounts: 3, writingBatches: 100, mediaCredits: 0, storageMb: 1000, members: 1 }
  }
];

export const TRIAL = {
  days: 14,
  connectedAccounts: 2,
  writingBatches: 10,
  mediaCredits: 1,
  storageMb: 200,
  cardRequired: false,
  autoConvert: false
} as const;

export function planById(id: string | null | undefined) {
  return plans.find((p) => p.id === id || p.planTermsId === id);
}

export function formatPrice(plan: Pick<Plan, 'priceCents' | 'currency'>) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: plan.currency,
    minimumFractionDigits: 0
  }).format(plan.priceCents / 100);
}
