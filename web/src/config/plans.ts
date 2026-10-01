/**
 * Public plan catalogue: the single source for prices on the site, in both catalog versions.
 *
 * - `legacy` (default): the Studio / Studio Assist packages and the 14-day trial. Mirrors
 *   `migrations/postriff/007_consumer_web_billing.sql` (pr_plan_terms). `status` follows decision D3:
 *   'proposed' until the commercial decision flips the database row to 'active'
 *   (see docs/postriff-consumer-web/billing-and-email.md).
 * - `v2` (Pricing v2, `pricing-v2-2026-09-28`): Free and Creator only, exactly as `GET /api/plans`
 *   (`plan_pricing.public_catalog`) projects the rows migration 048 seeds. `V2_CATALOG` must equal
 *   `docs/design/rafii-product-growth/contracts/pricing-catalog-v2.json`; a PostgreSQL test holds the
 *   database to the same file, so the public pages, the app and checkout cannot drift apart (PRD AC05).
 *
 * `NEXT_PUBLIC_PRICING_CATALOG` picks the version at build time. Nothing here charges anyone; checkout
 * is gated by the API on the live status. Import-free so `node --test` can load it directly.
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
 * `legacy` until Pricing v2 is activated, then `v2`. Set NEXT_PUBLIC_PRICING_CATALOG=v2 together with the
 * API's POSTRIFF_PRICING_V2_ENABLED=1, so the public pages and the app offer the same catalog; anything
 * else (unset, empty, a typo) keeps today's legacy catalog.
 */
export type PricingCatalogId = 'legacy' | 'v2';

export function pricingCatalogId(value: string | null | undefined): PricingCatalogId {
  return typeof value === 'string' && value.trim().toLowerCase() === 'v2' ? 'v2' : 'legacy';
}

/** Read once at build time (Next inlines NEXT_PUBLIC_* values). */
export const PRICING_CATALOG: PricingCatalogId = pricingCatalogId(process.env.NEXT_PUBLIC_PRICING_CATALOG);

/* ---------- Pricing v2: the public catalog projection ---------- */

/** `checkout` as `public_catalog` reports it. Only `available` may lead to a purchase; nothing else is a buy button. */
export type CatalogCheckout = 'available' | 'not_yet_available' | 'not_applicable' | 'legacy_flow';

export interface CatalogFirstValue {
  postDoctorRuns: number;
  genomeAnalyses: number;
  genomeMaxPosts: number;
}

/** One plan of `GET /api/plans`. */
export interface CatalogPlan {
  id: string;
  plan: string;
  label: string;
  priceCents: number;
  currency: string;
  interval: 'month' | null;
  entitlements: Record<string, number | string>;
  monthlyCredits?: number;
  firstValue?: CatalogFirstValue;
  checkout: CatalogCheckout;
  priceVariantId?: string | null;
}

/** `GET /api/plans`: the plans a new customer may see for sale (src/postriff_phase2/plan_pricing.py public_catalog). */
export interface PublicCatalog {
  catalogVersion: 'pricing-v2-2026-09-28' | 'legacy-2026-09';
  pricing: 'v2' | 'legacy';
  creditsPerUsd?: number;
  plans: CatalogPlan[];
  topUps: { available: boolean; reason: string };
  notes?: string[];
}

export const V2_CATALOG_VERSION = 'pricing-v2-2026-09-28';

/**
 * The v2 catalog as the API serves it for the rows migration 048 seeds: Free (US$0, no managed credits, one
 * Post Doctor check and one recent-20 Genome analysis) and Creator (US$59 default variant, 3,500 managed
 * credits a month, checkout not open until activation). Starter, Studio and top-ups are never listed.
 * Change it only together with the contract fixture and the database rows.
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
    }
  ],
  topUps: { available: false, reason: 'not_activated' },
  notes: [
    'Free has no monthly credits; it includes one Post Doctor check and one recent-20 Genome analysis.',
    'Creator credits reset each billing period and do not roll over. Paid work stops at the limit; nothing is charged silently.'
  ]
};

/** The v2 plan of one family ('free', 'creator'), or undefined when the catalog does not sell it. */
export function catalogPlan(plan: string, catalog: PublicCatalog = V2_CATALOG): CatalogPlan | undefined {
  return catalog.plans.find((p) => p.plan === plan);
}

/** A number from a plan's public entitlements; null when missing (never a guessed default). */
export function catalogLimit(plan: CatalogPlan, key: string): number | null {
  const value = key === 'monthlyCredits' ? (plan.monthlyCredits ?? plan.entitlements[key]) : plan.entitlements[key];
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
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
  highlights: string[];
  checkout: CatalogCheckout;
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
    highlights: present([
      first ? `${counted(first.postDoctorRuns, 'Post Doctor check')} on a draft of yours` : null,
      first ? `${counted(first.genomeAnalyses, 'analysis', 'analyses')} of up to ${countText(first.genomeMaxPosts)} recent posts` : null,
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
    tagline: 'Rafii in your weekly routine.',
    priceCents: plan.priceCents,
    currency: plan.currency,
    interval: plan.interval,
    highlights: present([
      credits !== null ? `${countText(credits)} managed AI credits every month` : null,
      'See each task’s credit limit before it runs',
      capacityLine(plan, true),
      'Credits reset each billing period; no rollover',
      'Stops at your limit — no silent overage'
    ]),
    checkout: plan.checkout
  };
}

/** Free and Creator, cheapest first, in the words the public cards use; numbers come from the catalog. */
export function v2PlanCards(catalog: PublicCatalog = V2_CATALOG): V2PlanCard[] {
  return catalog.plans.flatMap((plan) => (plan.plan === 'free' ? [freeCard(plan)] : plan.plan === 'creator' ? [creatorCard(plan)] : []));
}

/**
 * The one action a public v2 card offers. Every path starts with a free workspace, because checkout needs one:
 * `available` leads through sign-up to the in-app plan list; anything else is the honest free path with a
 * note, never a buy button that cannot work.
 */
export interface CardAction {
  label: string;
  href: string;
  note: string | null;
}

export function v2CardAction(card: Pick<V2PlanCard, 'plan' | 'name' | 'checkout'>, signUpHref: string): CardAction {
  if (card.plan === 'free') return { label: 'Start free', href: signUpHref, note: 'No card needed.' };
  if (card.checkout === 'available') {
    return { label: `Get ${card.name}`, href: `${signUpHref}?next=${encodeURIComponent('/app/account/billing#plans')}`, note: 'Start free, then choose it under Usage & plan.' };
  }
  return { label: 'Start free', href: signUpHref, note: `${card.name} checkout isn’t open yet. Start free now and choose ${card.name} from Usage & plan when it opens.` };
}

/** schema.org offers: only plans a customer can buy right now (legacy: active terms; v2: checkout available). */
export interface JsonLdOffer {
  '@type': 'Offer';
  name: string;
  price: string;
  priceCurrency: string;
  category: 'subscription';
}

export function jsonLdOffers(catalog: PricingCatalogId = PRICING_CATALOG, v2: PublicCatalog = V2_CATALOG): JsonLdOffer[] {
  const sellable =
    catalog === 'v2'
      ? v2.plans.filter((plan) => plan.checkout === 'available').map((plan) => ({ name: plan.label, priceCents: plan.priceCents, currency: plan.currency }))
      : plans.filter((plan) => plan.status === 'active').map((plan) => ({ name: plan.name, priceCents: plan.priceCents, currency: plan.currency }));
  return sellable.map((plan) => ({ '@type': 'Offer', name: plan.name, price: (plan.priceCents / 100).toFixed(2), priceCurrency: plan.currency, category: 'subscription' }));
}
