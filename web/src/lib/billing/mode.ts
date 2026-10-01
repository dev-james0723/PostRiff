/**
 * Pricing v2's billing contract read for the page and the work surfaces (spec §12.2, §13.3–13.4; PRD R-COM-04).
 * Pure and import-free (type-only imports) so `node --test` can load it directly.
 *
 * Every surface branches on the server's `billingMode`:
 * - `managed_credits` (Creator): a credit meter against the period's granted credits, its reset date and held credits;
 * - `free_preview` (Free): the preview actions left, never a 0 / 0 credit bar;
 * - `legacy_allowances`: the existing writing-batch and media-credit allowances.
 * Mode is never inferred from a price, a batch count or a wallet being present. Sources: `billing.py usage_view`,
 * `hosted.py usage`, `credit_wallet.py CreditBook.view`, `growth/service.py preview_status`.
 */
import type { BillingMode, CreditBalance, FreePreview, FreePreviewReason, PlanTerms, Usage } from '@/lib/api/types';

export const V2_CATALOG_VERSION = 'pricing-v2-2026-09-28';

const MODES: readonly string[] = ['free_preview', 'managed_credits', 'legacy_allowances'];

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * The response's billing mode. A response without the field predates the v2 contract, and only the legacy
 * allowance catalog ever sent those: that is a version default, not an inference. An unknown value is null,
 * so nothing mode-specific is shown rather than a guess.
 */
export function billingModeOf(usage: { billingMode?: unknown } | null | undefined): BillingMode | null {
  if (!usage) return null;
  if (usage.billingMode === undefined) return 'legacy_allowances';
  return typeof usage.billingMode === 'string' && MODES.includes(usage.billingMode) ? (usage.billingMode as BillingMode) : null;
}

/* ---------- managed credits ---------- */

/** Amber when 10% or less of the period's credits is left. */
export const CREDIT_WARN_RATIO = 0.1;
/** Credits that expire within three days are called out; unused credits do not roll over. */
export const EXPIRING_SOON_SECONDS = 3 * 86400;

/** Millicredits to credits at the 0.1-credit display resolution, truncated so what is left is never overstated. */
export function creditsFromMilli(milli: number): number {
  return Math.floor(Math.max(0, milli) / 100) / 10;
}

interface CreditReading {
  available: number;
  held: number;
  debt: number;
  /** When this period's credits expire (epoch seconds); null when no granted period is on record. */
  resetsAt: number | null;
  expiringSoon: boolean;
}

export type CreditMeter =
  | { kind: 'unavailable' }
  | ({ kind: 'measured'; total: number; fill: number; warn: boolean } & CreditReading)
  /** No bar: the period total is not on record yet, or more is available than this period granted. */
  | ({ kind: 'no_total'; reason: 'total_unknown' | 'above_period_grant' } & CreditReading);

export function creditMeter(credits: CreditBalance | null | undefined, now: number): CreditMeter {
  if (!credits) return { kind: 'unavailable' };
  const available = credits.availableMilliCredits;
  const held = credits.heldMilliCredits;
  const debt = credits.debtMilliCredits;
  if (!finite(available) || !finite(held) || !finite(debt) || available < 0 || held < 0 || debt < 0) return { kind: 'unavailable' };
  const expiry = credits.currentPeriodExpiresAt;
  const resetsAt = finite(expiry) && expiry > 0 ? expiry : null;
  const reading: CreditReading = {
    available: creditsFromMilli(available),
    held: creditsFromMilli(held),
    debt: creditsFromMilli(debt),
    resetsAt,
    expiringSoon: resetsAt !== null && resetsAt > now && resetsAt - now <= EXPIRING_SOON_SECONDS && available > 0
  };
  const grant = credits.currentPeriodGrantMilliCredits;
  if (!finite(grant) || grant <= 0) return { kind: 'no_total', reason: 'total_unknown', ...reading };
  if (available > grant) return { kind: 'no_total', reason: 'above_period_grant', ...reading };
  const ratio = available / grant;
  return { kind: 'measured', ...reading, total: creditsFromMilli(grant), fill: Math.min(1, Math.max(0, ratio)), warn: ratio <= CREDIT_WARN_RATIO };
}

/* ---------- Free preview ---------- */

export type PreviewKey = 'postDoctor' | 'genome';

export interface PreviewItem {
  key: PreviewKey;
  remaining: number;
  state: 'ready' | 'used' | 'unavailable';
  reason: FreePreviewReason | 'unknown' | null;
  /** The Genome analysis's post limit, when the API sends it. */
  maxPosts: number | null;
}

/** Each first-value action and what is left of it; null when the status could not be read (never shown as zero). */
export function freePreviewItems(preview: FreePreview | null | undefined): PreviewItem[] | null {
  if (!preview) return null;
  const rawMax = preview.genome?.maxPosts;
  const maxPosts = finite(rawMax) ? rawMax : null;
  return (['postDoctor', 'genome'] as const).map((key): PreviewItem => {
    const action = preview[key];
    const posts = key === 'genome' ? maxPosts : null;
    if (!action || !finite(action.remaining)) return { key, remaining: 0, state: 'unavailable', reason: 'unknown', maxPosts: posts };
    const remaining = Math.max(0, Math.floor(action.remaining));
    if (action.eligible && remaining > 0) return { key, remaining, state: 'ready', reason: null, maxPosts: posts };
    if (action.reason === 'used') return { key, remaining: 0, state: 'used', reason: 'used', maxPosts: posts };
    if (action.reason) return { key, remaining, state: 'unavailable', reason: action.reason, maxPosts: posts };
    if (remaining === 0) return { key, remaining: 0, state: 'used', reason: 'used', maxPosts: posts };
    return { key, remaining, state: 'unavailable', reason: 'unknown', maxPosts: posts };
  });
}

/* ---------- plans ---------- */

/** Which plan list the page shows: the v2 catalog (Free + Creator) or today's legacy plans. */
export function planListKind(usage: Pick<Usage, 'catalogVersion'>): 'v2' | 'legacy' {
  return usage.catalogVersion === V2_CATALOG_VERSION ? 'v2' : 'legacy';
}

const OPEN_STATUSES: readonly string[] = ['active', 'past_due', 'grace'];

/**
 * What a v2 plan card's footer offers. `checkout` only when it can work: the terms are active and open for new
 * checkout, the server says checkout is available, this workspace has its own price, and nothing else is held.
 * Free is never bought (a workspace returns to it when a paid plan ends); a held subscription changes in the portal.
 */
export type V2Offer = 'current' | 'owner_only' | 'checkout' | 'not_open' | 'none';

export interface V2PlanCardModel {
  terms: PlanTerms;
  current: boolean;
  /** What this workspace pays or would pay; null when it has no price of its own yet (never the experiment). */
  priceCents: number | null;
  currency: string;
  offer: V2Offer;
}

type PlanInput = Pick<Usage, 'planTerms' | 'entitlement' | 'subscription' | 'creatorOffer' | 'lifecycle' | 'billing'>;

function priceFor(terms: PlanTerms, usage: PlanInput): { priceCents: number | null; currency: string } {
  if (terms.plan === 'free') return { priceCents: terms.priceCents, currency: terms.currency };
  const sub = usage.subscription;
  if (sub && sub.planTermsId === terms.id && terms.id === usage.entitlement?.planTermsId) return { priceCents: sub.priceCents, currency: sub.currency };
  const offer = usage.creatorOffer;
  if (offer && offer.planTermsId === terms.id) return { priceCents: offer.amountCents, currency: offer.currency };
  return { priceCents: null, currency: terms.currency };
}

/** The v2 plan list: plans for new sale only (Free and Creator at launch), cheapest first, one row per plan. */
export function v2PlanCardModels(usage: PlanInput, isOwner: boolean): V2PlanCardModel[] {
  const currentId = usage.entitlement?.planTermsId;
  const byPlan = new Map<string, PlanTerms>();
  for (const row of usage.planTerms) {
    if (row.catalogState !== 'public' || row.status === 'retired') continue;
    const held = byPlan.get(row.plan);
    if (!held || (row.id === currentId && held.id !== currentId) || (held.id !== currentId && row.version > held.version)) byPlan.set(row.plan, row);
  }
  const open = OPEN_STATUSES.includes(usage.lifecycle?.status ?? '');
  return [...byPlan.values()]
    .sort((a, b) => a.priceCents - b.priceCents || a.plan.localeCompare(b.plan))
    .map((terms) => {
      const current = terms.id === currentId;
      const { priceCents, currency } = priceFor(terms, usage);
      let offer: V2Offer;
      if (current) offer = 'current';
      else if (!isOwner) offer = 'owner_only';
      else if (terms.plan === 'free' || open) offer = 'none';
      else if (terms.status === 'active' && terms.newCheckoutEnabled && usage.billing?.checkoutAvailable === true) offer = priceCents !== null ? 'checkout' : 'none';
      else offer = 'not_open';
      return { terms, current, priceCents, currency, offer };
    });
}

/** A paid legacy package (Studio, Studio Assist) kept for this workspace while v2 sells something else. */
export function isLegacyPlanUnderV2(usage: Pick<Usage, 'catalogVersion' | 'billingMode' | 'planTerms' | 'entitlement'>): boolean {
  if (planListKind(usage) !== 'v2' || billingModeOf(usage) !== 'legacy_allowances') return false;
  const held = usage.planTerms.find((row) => row.id === usage.entitlement?.planTermsId);
  return Boolean(held && held.catalogState === 'legacy' && held.plan !== 'trial');
}

/* ---------- work surfaces ---------- */

/** What paid drafting draws on for this workspace: legacy batches, managed credits, or nothing on Free. */
export type WritingAllowance =
  | { kind: 'loading' }
  | { kind: 'unavailable' }
  | { kind: 'batches'; remaining: number; resetsAt: number | null }
  | { kind: 'credits'; available: number; resetsAt: number | null; debt: number }
  | { kind: 'free' };

export function writingAllowance(query: { isLoading?: boolean; isError?: boolean; data?: Usage | null }): WritingAllowance {
  if (query.isLoading) return { kind: 'loading' };
  const data = query.data;
  if (query.isError || !data) return { kind: 'unavailable' };
  const mode = billingModeOf(data);
  if (mode === 'free_preview') return { kind: 'free' };
  // A legacy credit pilot spends its wallet (charge_batch is off for credit reservations), so it reads as credits too.
  if (mode === 'managed_credits' || (mode === 'legacy_allowances' && data.credits)) {
    const meter = creditMeter(data.credits, 0);
    return meter.kind === 'unavailable' ? { kind: 'unavailable' } : { kind: 'credits', available: meter.available, resetsAt: meter.resetsAt, debt: meter.debt };
  }
  if (mode === 'legacy_allowances') {
    const remaining = data.entitlement?.writingBatchesRemaining;
    return finite(remaining) ? { kind: 'batches', remaining, resetsAt: data.entitlement.resetsAt ?? null } : { kind: 'unavailable' };
  }
  return { kind: 'unavailable' };
}

/** Writing batches at or below this many left are worth a reminder (legacy). */
export const WRITING_LOW = 2;

export type AllowanceReminder =
  | { kind: 'batches'; left: number; resetsAt: number | null }
  | { kind: 'credits_out'; resetsAt: number | null }
  | { kind: 'credits_low'; left: number; resetsAt: number | null }
  | { kind: 'credits_debt'; debt: number }
  | null;

/** The one allowance reminder worth acting on, by mode. Free has no recurring allowance, so it never gets one. */
export function allowanceReminder(usage: Usage | null | undefined, now: number): AllowanceReminder {
  if (!usage) return null;
  const allowance = writingAllowance({ data: usage });
  if (allowance.kind === 'batches') return allowance.remaining <= WRITING_LOW ? { kind: 'batches', left: Math.max(0, allowance.remaining), resetsAt: allowance.resetsAt } : null;
  if (allowance.kind !== 'credits') return null;
  const meter = creditMeter(usage.credits, now);
  if (meter.kind === 'unavailable') return null;
  if (meter.debt > 0) return { kind: 'credits_debt', debt: meter.debt };
  if (meter.available <= 0) return { kind: 'credits_out', resetsAt: meter.resetsAt };
  if (meter.kind === 'measured' && meter.warn) return { kind: 'credits_low', left: meter.available, resetsAt: meter.resetsAt };
  return null;
}

/** How a writer is paid for here: the API's cost class read against what this workspace spends. */
export type CostClassKey = 'none' | 'subscription' | 'batches' | 'credits' | 'free_plan' | 'paid' | 'unreported' | 'other';

export function costClassKey(costClass: string | undefined, allowance: WritingAllowance): CostClassKey {
  switch (costClass) {
    case 'none':
      return 'none';
    case 'subscription':
      return 'subscription';
    case 'paid':
      return allowance.kind === 'batches' ? 'batches' : allowance.kind === 'credits' ? 'credits' : allowance.kind === 'free' ? 'free_plan' : 'paid';
    case undefined:
    case '':
      return 'unreported';
    default:
      return 'other';
  }
}
