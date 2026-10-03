/**
 * Public prospects always see Free and proposed Starter, Creator and Studio. Legacy data below is retained
 * for compatibility; it is never a new-sale catalog or a public rollback destination.
 *
 * - Legacy data: the Studio / Studio Assist packages and the 14-day trial. Mirrors
 *   `migrations/postriff/007_consumer_web_billing.sql` (pr_plan_terms). `status` follows decision D3:
 *   'proposed' until the commercial decision flips the database row to 'active'
 *   (see docs/postriff-consumer-web/billing-and-email.md).
 * - `v2` (Pricing v2, `pricing-v2-2026-09-28`): Free and proposed Starter, Creator and Studio. `V2_CATALOG`
 *   follows the committed display fixture at
 *   `docs/design/rafii-product-growth/contracts/pricing-catalog-v2.json`.
 *
 * No public selector activates billing or provider work. OFF/rollback keeps Free available
 * and paid plans unavailable; a qualified catalog may advertise a route to server-verified checkout.
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

export function formatPrice(plan: { priceCents: number; currency: string }) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: plan.currency,
    minimumFractionDigits: 0
  }).format(plan.priceCents / 100);
}

/* ---------- which catalog the site sells from ---------- */

/**
 * Compatibility input only: unset, legacy, OFF and v2 all retain the approved four-plan
 * public surface. Production checkout flags belong to the server; rollback is unavailable/waitlist.
 */
export type PricingCatalogId = 'legacy' | 'v2';

export function pricingCatalogId(_value: string | null | undefined): PricingCatalogId {
  return 'v2';
}

/** Read once at build time (Next inlines NEXT_PUBLIC_* values). */
export const PRICING_CATALOG: PricingCatalogId = pricingCatalogId(process.env.NEXT_PUBLIC_PRICING_CATALOG);

/* ---------- Pricing v2: the public catalog projection ---------- */

import type { CatalogCheckout, CatalogPlan, PublicCatalog } from '../lib/api/types';
export type { CatalogCheckout, CatalogFirstValue, CatalogPlan, PublicCatalog } from '../lib/api/types';

export const V2_CATALOG_VERSION = 'pricing-v2-2026-09-28';

/**
 * The committed v2 display fixture: Free (US$0, no managed credits, one eligible
 * Post Doctor check and one recent-20 Genome analysis when available) and Creator (US$59 default variant, 3,500 managed
 * credits a month, checkout not open until activation). Starter (US$29 / 1,000 credits) and Studio (US$149 / 8,000 credits) are also proposed. Top-ups are never listed.
 * It does not prove that a preview or purchase is enabled for a visitor.
 */
export const V2_CATALOG: PublicCatalog = {
  catalogVersion: 'pricing-v2-2026-09-28',
  pricing: 'v2',
  creditsPerUsd: 300,
  plans: [
    {
      id: 'free-v1',
      plan: 'free',
      label: 'Free',
      priceCents: 0,
      currency: 'USD',
      interval: null,
      entitlements: { members: 1, connectedAccounts: 1, brands: 1, storageMb: 200, writingBatches: 0, mediaCredits: 0, overage: 'stop' },
      monthlyCredits: 0,
      firstValue: { postDoctorRuns: 1, genomeAnalyses: 1, genomeMaxPosts: 20 },
      checkout: 'not_applicable'
    },
    {
      "id": "starter-v1",
      "plan": "starter",
      "label": "Starter",
      "priceCents": 2900,
      "currency": "USD",
      "interval": "month",
      "entitlements": {"members": 1, "connectedAccounts": 3, "brands": 1, "storageMb": 1000, "monthlyCredits": 1000, "writingBatches": 0, "mediaCredits": 0, "overage": "stop"},
      "monthlyCredits": 1000,
      "checkout": "not_yet_available",
    },
    {
      id: 'creator-v1',
      plan: 'creator',
      label: 'Creator',
      priceCents: 5900,
      currency: 'USD',
      interval: 'month',
      entitlements: { members: 1, connectedAccounts: 6, brands: 2, storageMb: 1000, monthlyCredits: 3500, writingBatches: 0, mediaCredits: 0, overage: 'stop' },
      monthlyCredits: 3500,
      checkout: 'not_yet_available',
      priceVariantId: 'creator-59-v1'
    },
    {
      "id": "studio-v2",
      "plan": "studio",
      "label": "Studio",
      "priceCents": 14900,
      "currency": "USD",
      "interval": "month",
      "entitlements": {"members": 3, "connectedAccounts": 10, "brands": 3, "storageMb": 1000, "monthlyCredits": 8000, "writingBatches": 0, "mediaCredits": 0, "overage": "stop"},
      "monthlyCredits": 8000,
      "checkout": "not_yet_available",
    },
  ],
  topUps: { available: false, reason: 'not_activated' },
  notes: [
    'Free has no monthly credits; it includes one Post Doctor check and one recent-20 Genome analysis.',
    'Paid plan credits reset each billing period and do not roll over. Paid work stops at the limit; nothing is charged silently.'
  ]
};

/** The v2 plan of one family ('free', 'starter', 'creator', 'studio'), or undefined when the catalog does not sell it. */
export function catalogPlan(plan: string, catalog: PublicCatalog = V2_CATALOG): CatalogPlan | undefined {
  return catalog.plans.find((p) => p.plan === plan && isV2PublicPlan(p));
}

/** Only the approved v2 identities belong on the public surface; legacy Studio remains historical. */
export function isV2PublicPlan(plan: Pick<CatalogPlan, 'id' | 'plan'>): boolean {
  return ({ free: 'free-v1', starter: 'starter-v1', creator: 'creator-v1', studio: 'studio-v2' } as Record<string, string>)[plan.plan] === plan.id;
}

/** A safe quantity from the public projection; unknown monthly credits never fall back to entitlements. */
export function catalogLimit(plan: CatalogPlan, key: string): number | null {
  const value = key === 'monthlyCredits' ? plan.monthlyCredits : plan.entitlements[key];
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

/** "US$59" for prose; cards use `formatPrice` ("$59") next to the "Prices are shown in USD" note. */
export function usdText(priceCents: number): string {
  const amount = priceCents / 100;
  return `US$${Number.isInteger(amount) ? amount.toLocaleString('en-US') : amount.toFixed(2)}`;
}

/** Whole numbers as the site writes them: "3,500". */
export function countText(value: number): string {
  return value.toLocaleString('en-US');
}

/* ---------- Pricing v2: what the public plan cards say ---------- */

export interface V2PlanCard {
  /** Plan terms id (`free-v1`, `creator-v1`). */
  id: string;
  plan: string;
  name: string;
  tagline: string;
  priceCents: number;
  currency: string;
  interval: 'month' | null;
  monthlyCredits: number | null;
  highlights: string[];
  checkout: CatalogCheckout;
  /** Explicit server-qualified catalog availability, never inferred from a public flag. */
  checkoutAvailable?: boolean;
}

function counted(value: number, noun: string, plural = `${noun}s`) {
  return `${value === 1 ? 'One' : countText(value)} ${value === 1 ? noun : plural}`;
}

function capacityLine(plan: CatalogPlan, upTo: boolean): string | null {
  const accounts = catalogLimit(plan, 'connectedAccounts');
  const brands = catalogLimit(plan, 'brands');
  const seats = catalogLimit(plan, 'members');
  if (accounts === null || brands === null || seats === null) return null;
  const limit = (value: number, noun: string) => `${upTo && value > 1 ? 'up to ' : ''}${countText(value)} ${value === 1 ? noun : `${noun}s`}`;
  const line = `${limit(accounts, 'connected account')} · ${limit(brands, 'brand')} · ${countText(seats)} seat${seats === 1 ? '' : 's'}`;
  return line.charAt(0).toUpperCase() + line.slice(1);
}

function present(items: (string | null)[]): string[] {
  return items.filter((item): item is string => item !== null);
}

function freeCard(plan: CatalogPlan): V2PlanCard {
  const first = plan.firstValue;
  return {
    id: plan.id,
    plan: plan.plan,
    name: plan.label,
    tagline: 'See Rafii work on your own writing.',
    priceCents: plan.priceCents,
    currency: plan.currency,
    interval: plan.interval,
    monthlyCredits: catalogLimit(plan, 'monthlyCredits'),
    highlights: present([
      first ? `${counted(first.postDoctorRuns, 'Post Doctor check')} on a draft of yours, when available` : null,
      first ? `${counted(first.genomeAnalyses, 'analysis', 'analyses')} of up to ${countText(first.genomeMaxPosts)} recent posts, when available` : null,
      capacityLine(plan, false),
      'Draft, edit, approve and export, any time',
      'No monthly AI credits, so nothing is ever charged'
    ]),
    checkout: plan.checkout
  };
}

function creatorCard(plan: CatalogPlan): V2PlanCard {
  const credits = catalogLimit(plan, 'monthlyCredits');
  return {
    id: plan.id,
    plan: plan.plan,
    name: plan.label,
    tagline: plan.plan === 'starter' ? 'Start your managed AI routine.' : plan.plan === 'studio' ? 'More room for your team’s work.' : 'Rafii in your weekly routine.',
    priceCents: plan.priceCents,
    currency: plan.currency,
    interval: plan.interval,
    monthlyCredits: credits,
    highlights: present([
      credits !== null ? `${countText(credits)} managed AI credits every month` : 'Managed credit allowance unavailable',
      'See each task’s credit limit before it runs',
      capacityLine(plan, true),
      'Credits reset each billing period; no rollover',
      'Stops at your limit — no silent overage'
    ]),
    checkout: plan.checkout,
    checkoutAvailable: credits !== null && plan.checkout === 'available' && plan.checkoutAvailable === true
  };
}

/** Free, Starter, Creator and Studio, cheapest first, in the words the public cards use; numbers come from the catalog. */
export function v2PlanCards(catalog: PublicCatalog = V2_CATALOG): V2PlanCard[] {
  return catalog.plans.filter(isV2PublicPlan).flatMap((plan) => (plan.plan === 'free' ? [freeCard(plan)] : ['starter', 'creator', 'studio'].includes(plan.plan) ? [creatorCard(plan)] : []));
}

/**
 * Signup always starts on Free. Creator has no action until the sanitized catalog explicitly
 * reports qualified availability. A navigation link never authorizes checkout or provider spend.
 */
export interface CardAction {
  label: string;
  href: string | null;
  note: string | null;
}

export function v2CardAction(card: Pick<V2PlanCard, 'plan' | 'name' | 'checkout' | 'checkoutAvailable' | 'monthlyCredits'>, signUpHref: string): CardAction {
  if (card.plan === 'free') return { label: 'Start free', href: signUpHref, note: 'No card needed.' };
  if (card.plan === 'creator' && typeof card.monthlyCredits === 'number' && Number.isSafeInteger(card.monthlyCredits) && card.monthlyCredits >= 0 && card.checkout === 'available' && card.checkoutAvailable === true) {
    return { label: `Get ${card.name}`, href: `${signUpHref}?next=${encodeURIComponent('/app/account/billing#plans')}`, note: 'Start free, then review Creator under Usage & plan. Checkout eligibility is verified by the server.' };
  }
  return { label: `${card.name} unavailable`, href: null, note: `${card.name} is proposed and it is not available for purchase. You can start on Free.` };
}

/** schema.org: Free, plus the default Creator offer only with explicit qualified availability. */
export interface JsonLdOffer {
  '@type': 'Offer';
  name: string;
  price: string;
  priceCurrency: string;
  category: 'subscription';
}

export function jsonLdOffers(catalog: PricingCatalogId = PRICING_CATALOG, v2: PublicCatalog = V2_CATALOG): JsonLdOffer[] {
  void catalog;
  const sellable = v2.plans.filter((plan) =>
    (plan.plan === 'free' && plan.priceCents === 0) ||
    (plan.plan === 'creator' && plan.priceCents === 5900 && plan.currency === 'USD' && catalogLimit(plan, 'monthlyCredits') !== null && plan.checkout === 'available' && plan.checkoutAvailable === true)
  ).map((plan) => ({ name: plan.label, priceCents: plan.priceCents, currency: plan.currency }));
  return sellable.map((plan): JsonLdOffer => ({ '@type': 'Offer', name: plan.name, price: (plan.priceCents / 100).toFixed(2), priceCurrency: plan.currency, category: 'subscription' }));
}
