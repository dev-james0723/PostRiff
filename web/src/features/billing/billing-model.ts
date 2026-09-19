/**
 * Pure reading of `GET /usage` for the Usage & plan page. No React, no fetching: every
 * function takes API values and returns what the page should say about them, so the
 * rules (what "Unavailable" means, when a bar turns amber, which plan row is offered)
 * live in one place and can be checked without rendering.
 *
 * Sources: `src/postriff_phase2/billing.py` (usage_view, lifecycle, availability, reserve,
 * settle), `hosted.py` (usage, members, billing_checkout) and migration 007 (plan terms,
 * subscription statuses, ledger kinds).
 */
import type { ChannelView, LedgerEntry, Member, PlanTerms, Usage } from '@/lib/api/types';
import { isConnected } from '@/lib/channels/state';
import { daysUntil } from '@/lib/time';

/* ---------- lifecycle ---------- */

/** Tones shared with `AnimatedBadge` (minus `loading`, which only the checkout confirmation uses). */
export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

/**
 * Badge tone for `lifecycle.status` (never the raw `subscription.status`: `usage_view` reads the row
 * before `lifecycle` updates it, so the two can differ inside one response).
 * `grace` is kept for completeness; the Stripe mapping (`billing_stripe.py`) never produces it today.
 */
export function lifecycleTone(status: string | null | undefined): Tone {
  switch (status) {
    case 'trial':
      return 'info';
    case 'active':
      return 'success';
    case 'past_due':
      return 'danger';
    case 'grace':
      return 'warning';
    default:
      return 'neutral';
  }
}

/** The statuses `billing_checkout` refuses with 409 ("already has a subscription"). Cancelled and expired may buy again. */
export const OPEN_SUBSCRIPTION_STATUSES: readonly string[] = ['active', 'past_due', 'grace'];

export function hasOpenSubscription(status: string | null | undefined): boolean {
  return typeof status === 'string' && OPEN_SUBSCRIPTION_STATUSES.includes(status);
}

export function isTrial(usage: Pick<Usage, 'lifecycle'>): boolean {
  return usage.lifecycle?.status === 'trial';
}

/** The next date that changes something for this workspace, as data; the copy module words it. */
export type PlanTimeline =
  | { kind: 'trial_left'; endsAt: number; daysLeft: number }
  | { kind: 'trial_ended'; endedAt: number }
  | { kind: 'renews'; at: number }
  | { kind: 'ends'; at: number }
  | { kind: 'grace'; until: number | null }
  | { kind: 'ended'; at: number | null }
  | { kind: 'unavailable'; what: 'trial_end' | 'renewal' };

export function planTimeline(usage: Pick<Usage, 'lifecycle' | 'entitlement' | 'subscription'>, now = Date.now() / 1000): PlanTimeline {
  const status = usage.lifecycle?.status;
  const sub = usage.subscription;
  if (status === 'trial') {
    // A trial's `resetsAt` is `pr_trials.expires_at` (billing.py ensure_entitlement): the end, not a reset.
    const endsAt = usage.entitlement?.resetsAt ?? null;
    const days = daysUntil(endsAt, now);
    if (endsAt === null || days === null) return { kind: 'unavailable', what: 'trial_end' };
    return days > 0 ? { kind: 'trial_left', endsAt, daysLeft: days } : { kind: 'trial_ended', endedAt: endsAt };
  }
  if (status === 'past_due' || status === 'grace') return { kind: 'grace', until: sub?.graceUntil ?? null };
  if (status === 'cancelled' || status === 'expired') return { kind: 'ended', at: sub?.currentPeriodEnd ?? null };
  const at = sub?.currentPeriodEnd ?? null;
  if (at === null) return { kind: 'unavailable', what: 'renewal' };
  return sub?.cancelAtPeriodEnd ? { kind: 'ends', at } : { kind: 'renews', at };
}

/** What the top-of-page alert should say, or null when nothing needs attention. */
export type LifecycleAlert =
  | { kind: 'payment_failed'; graceUntil: number | null }
  | { kind: 'ended'; at: number | null }
  | { kind: 'trial_ended'; at: number }
  | { kind: 'ending'; at: number };

export function lifecycleAlert(usage: Pick<Usage, 'lifecycle' | 'entitlement' | 'subscription'>, now = Date.now() / 1000): LifecycleAlert | null {
  const status = usage.lifecycle?.status;
  if (!status) return null;
  const timeline = planTimeline(usage, now);
  switch (timeline.kind) {
    case 'grace':
      return { kind: 'payment_failed', graceUntil: timeline.until };
    case 'ended':
      return { kind: 'ended', at: timeline.at };
    case 'trial_ended':
      return { kind: 'trial_ended', at: timeline.endedAt };
    case 'ends':
      return status === 'active' ? { kind: 'ending', at: timeline.at } : null;
    default:
      return null;
  }
}

/* ---------- plans ---------- */

function preferRow(candidate: PlanTerms, held: PlanTerms, currentTermsId: string | null | undefined) {
  const rank = (row: PlanTerms) => [row.id === currentTermsId ? 1 : 0, row.status === 'active' ? 1 : 0, row.version] as const;
  const a = rank(candidate);
  const b = rank(held);
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return a[i] > b[i];
  }
  return false;
}

/**
 * One row per purchasable plan. Trial and retired rows are dropped. Within a plan the row the
 * workspace is on wins (so "Current" and its numbers match what it has); otherwise the highest
 * active version; otherwise the highest version. Cheapest first.
 */
export function latestTermsPerPlan(terms: readonly PlanTerms[], currentTermsId?: string | null): PlanTerms[] {
  const byPlan = new Map<string, PlanTerms>();
  for (const row of terms) {
    if (row.plan === 'trial' || row.status === 'retired') continue;
    const held = byPlan.get(row.plan);
    if (!held || preferRow(row, held, currentTermsId)) byPlan.set(row.plan, row);
  }
  return [...byPlan.values()].toSorted((a, b) => a.priceCents - b.priceCents || a.plan.localeCompare(b.plan));
}

/** The terms row the entitlement was built from, if the API listed it. */
export function currentTerms(usage: Pick<Usage, 'planTerms' | 'entitlement'>): PlanTerms | undefined {
  return usage.planTerms.find((row) => row.id === usage.entitlement.planTermsId);
}

/** A plan allowance from `entitlements` jsonb: a finite, non-negative number, or null when missing or malformed. Never a fallback constant. */
export function allowanceTotal(terms: Pick<PlanTerms, 'entitlements'> | null | undefined, key: string): number | null {
  const value = terms?.entitlements?.[key];
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

/**
 * What a plan card's footer offers, in the order the backend would refuse a checkout. A plan the
 * workspace is on only counts as "current" while its subscription is open: after a cancellation
 * the same plan may be bought again (`billing_checkout` blocks only active, past_due and grace).
 */
export type PlanOffer = 'current' | 'owner_only' | 'switch_in_portal' | 'not_available' | 'checkout';

export function planOffer(input: {
  terms: Pick<PlanTerms, 'id' | 'status'>;
  currentTermsId: string | null | undefined;
  lifecycleStatus: string | null | undefined;
  checkoutAvailable: boolean | undefined;
  isOwner: boolean;
}): PlanOffer {
  const open = hasOpenSubscription(input.lifecycleStatus);
  if (input.terms.id === input.currentTermsId && open) return 'current';
  if (!input.isOwner) return 'owner_only';
  if (open) return 'switch_in_portal';
  if (!input.checkoutAvailable || input.terms.status !== 'active') return 'not_available';
  return 'checkout';
}

/* ---------- meters ---------- */

/** `remaining` counts down (writing batches, media credits); `used` counts up (accounts, members). */
export type MeterMode = 'remaining' | 'used';

export type MeterState =
  | { kind: 'pending' }
  | { kind: 'unavailable' }
  | { kind: 'not_included'; value: number | null }
  | { kind: 'no_total'; value: number }
  | { kind: 'measured'; mode: MeterMode; value: number; total: number; fill: number; warn: boolean; over: boolean };

/** Amber when 10% or less is left of a countdown allowance. */
export const REMAINING_WARN_RATIO = 0.1;
/** Amber when 90% or more of a seat-style allowance is in use. */
export const USED_WARN_RATIO = 0.9;

function finite(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * One reading per meter. Missing data is `unavailable` (never 0); a total of 0 is `not_included`
 * (no empty "0 / 0" bar); a value without a total is `no_total` (no bar, no invented maximum).
 * `fill` is 0..1 of the bar; `warn` follows the meter's mode.
 */
export function meterState(input: {
  mode: MeterMode;
  value: number | null | undefined;
  total: number | null | undefined;
  pending?: boolean;
  error?: boolean;
}): MeterState {
  if (input.pending) return { kind: 'pending' };
  if (input.error || !finite(input.value)) return { kind: 'unavailable' };
  const value = input.value;
  if (!finite(input.total) || input.total < 0) return { kind: 'no_total', value };
  const total = input.total;
  if (total === 0) return { kind: 'not_included', value };
  const ratio = value / total;
  const fill = Math.min(1, Math.max(0, ratio));
  const warn = input.mode === 'remaining' ? ratio <= REMAINING_WARN_RATIO : ratio >= USED_WARN_RATIO;
  const over = input.mode === 'used' && value > total;
  return { kind: 'measured', mode: input.mode, value, total, fill, warn, over };
}

/** Accounts that count toward the plan: the Channels page's own "connected" rule (`isConnected`). */
export function connectedAccountCount(channels: readonly ChannelView[]): number {
  return channels.filter((channel) => isConnected(channel)).length;
}

/** Memberships that hold a seat. `pr_memberships.status` is 'active' or 'revoked' (migration 001). */
export function activeMemberCount(members: readonly Pick<Member, 'status'>[]): number {
  return members.filter((member) => member.status === 'active').length;
}

/** The workspace cost ceiling as a used-mode reading; amber from the API's own warning line. */
export function costGuardState(budget: Usage['budget']) {
  const committed = budget.spentUsdMicro + budget.reservedUsdMicro;
  const fill = budget.stopUsdMicro > 0 ? Math.min(1, Math.max(0, committed / budget.stopUsdMicro)) : 0;
  return { committed, fill, warn: committed >= budget.warnUsdMicro, stopped: committed >= budget.stopUsdMicro };
}

/* ---------- checkout confirmation ---------- */

export const CONFIRM_FIRST_DELAY_MS = 2_000;
export const CONFIRM_MAX_DELAY_MS = 10_000;
export const CONFIRM_DEADLINE_MS = 120_000;

/** 2s, 4s, 8s, then every 10s: each `GET /usage` is a write transaction, so polling backs off. */
export function confirmPollDelay(attempt: number): number {
  return Math.min(CONFIRM_FIRST_DELAY_MS * 2 ** Math.max(0, attempt), CONFIRM_MAX_DELAY_MS);
}

/* ---------- ledger ---------- */

export type LedgerFilter = 'all' | 'writing' | 'media' | 'other';
export const LEDGER_FILTERS: readonly LedgerFilter[] = ['all', 'writing', 'media', 'other'];
export const LEDGER_PAGE = 20;

export function ledgerGroup(entry: Pick<LedgerEntry, 'dimension'>): Exclude<LedgerFilter, 'all'> {
  if (entry.dimension === 'text_model') return 'writing';
  if (entry.dimension === 'image_generation') return 'media';
  return 'other';
}

export function filterLedger<T extends Pick<LedgerEntry, 'dimension'>>(entries: readonly T[], filter: LedgerFilter): T[] {
  return filter === 'all' ? [...entries] : entries.filter((entry) => ledgerGroup(entry) === filter);
}

export function ledgerCounts(entries: readonly Pick<LedgerEntry, 'dimension'>[]): Record<LedgerFilter, number> {
  const counts: Record<LedgerFilter, number> = { all: entries.length, writing: 0, media: 0, other: 0 };
  for (const entry of entries) counts[ledgerGroup(entry)] += 1;
  return counts;
}

/** Sentence case for a value the maps below do not know yet ("new_kind" → "New kind"). */
export function humanize(value: string): string {
  const text = value.replace(/_/g, ' ').trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : '—';
}

const DIMENSIONS: Record<string, string> = {
  text_model: 'Writing',
  image_generation: 'Media',
  tool: 'Tool',
  storage: 'Storage',
  action: 'Action'
};

const STEPS: Record<string, string> = {
  reserve: 'Reserved',
  settle: 'Settled',
  release: 'Released (failed run)',
  adjust: 'Adjusted'
};

const COST_STATES: Record<string, { label: string; tone: Tone }> = {
  actual: { label: 'Actual cost', tone: 'success' },
  estimated: { label: 'Estimate', tone: 'info' },
  estimated_unknown: { label: 'Awaiting provider', tone: 'warning' },
  released: { label: 'Released', tone: 'neutral' }
};

export const dimensionLabel = (dimension: string) => DIMENSIONS[dimension] ?? humanize(dimension);
export const stepLabel = (kind: string) => STEPS[kind] ?? humanize(kind);
export const costStateOf = (state: string) => COST_STATES[state] ?? { label: humanize(state), tone: 'neutral' as Tone };

/** A run that reserved nothing and cost nothing: no paid model (ideas.py reserves 0 with charge_batch=false). */
export function isZeroCostRun(entry: Pick<LedgerEntry, 'estimatedUsdMicro' | 'actualUsdMicro'>): boolean {
  return entry.estimatedUsdMicro === 0 && (entry.actualUsdMicro === null || entry.actualUsdMicro === 0);
}

/**
 * What a row did to the allowance. Reads `chargeBatch` only when the API sends it (it does not yet:
 * `usage_view` omits the column); without it the answer is null rather than a guess.
 */
export function allowanceNote(entry: Pick<LedgerEntry, 'kind' | 'dimension' | 'costState'>): string | null {
  const charge = (entry as { chargeBatch?: unknown }).chargeBatch;
  if (typeof charge !== 'boolean') return null;
  if (!charge) return 'No allowance used';
  const unit = entry.dimension === 'image_generation' ? 'media credit' : 'writing batch';
  if (entry.kind === 'reserve') return `Needs a ${unit}`;
  if (entry.kind === 'release') return `${humanize(unit)} not used`;
  if (entry.kind === 'settle' && entry.costState === 'actual') return `Used a ${unit}`;
  return `${humanize(unit)} not counted yet`;
}

const CSV_FORMULA = /^[=+\-@\t\r]/;

function csvCell(value: string | number | null, text = true): string {
  if (value === null) return '';
  let cell = String(value);
  // A spreadsheet would run a text cell that starts like a formula; numbers are written by us and stay as they are.
  if (text && CSV_FORMULA.test(cell)) cell = `'${cell}`;
  return /[",\n\r]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;
}

const dollars = (micro: number | null) => (micro === null ? null : (micro / 1_000_000).toFixed(6));

/** CSV of the rows the page already holds; nothing is fetched. Times are UTC ISO-8601, money in USD. */
export function ledgerCsv(entries: readonly LedgerEntry[]): string {
  const header = ['time_utc', 'what', 'step', 'provider', 'model', 'estimated_usd', 'actual_usd', 'state', 'allowance'];
  const rows = entries.map((entry) =>
    [
      csvCell(new Date(entry.at * 1000).toISOString()),
      csvCell(dimensionLabel(entry.dimension)),
      csvCell(stepLabel(entry.kind)),
      csvCell(entry.provider || null),
      csvCell(entry.model || null),
      csvCell(dollars(entry.estimatedUsdMicro), false),
      csvCell(dollars(entry.actualUsdMicro), false),
      csvCell(costStateOf(entry.costState).label),
      csvCell(allowanceNote(entry) ?? (isZeroCostRun(entry) ? '$0 run' : null))
    ].join(',')
  );
  return [header.join(','), ...rows].join('\r\n') + '\r\n';
}
