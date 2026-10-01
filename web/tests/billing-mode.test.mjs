/**
 * Usage & plan and work surfaces by billing mode (Pricing v2 Tasks 8–9; spec §12.2, §13.3–13.4; PRD R-COM-04, AC05).
 * Every view branches on the server's `billingMode`, never on a price, a batch count or a wallet being present:
 * managed credits get a credit meter (grant, reset, held, no silent overage), Free gets its preview actions (never a
 * 0/0 bar), legacy keeps its allowances. Plan cards offer Free and Creator only under v2, at this workspace's price.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CREDIT_WARN_RATIO,
  allowanceReminder,
  billingModeOf,
  costClassKey,
  creditMeter,
  creditsFromMilli,
  freePreviewItems,
  isLegacyPlanUnderV2,
  planListKind,
  v2PlanCardModels,
  writingAllowance
} from '../src/lib/billing/mode.ts';
import { BILLING_COPY, copyLocale, billingCopy } from '../src/lib/billing/mode-copy.ts';

const NOW = 1_800_000_000;
const DAY = 86400;
const V2 = 'pricing-v2-2026-09-28';

const terms = (id, plan, extra = {}) => ({
  id,
  plan,
  version: 1,
  label: { free: 'Free', creator: 'Creator', studio: 'Studio', assist: 'Studio Assist', trial: 'Trial', starter: 'Starter' }[plan],
  priceCents: { free: 0, creator: 5900, studio: 1900, assist: 3900, trial: 0, starter: 2900 }[plan],
  currency: 'USD',
  status: plan === 'creator' ? 'proposed' : 'active',
  priceLabel: 'active',
  entitlements: {
    free: { members: 1, connectedAccounts: 1, brands: 1 },
    creator: { members: 1, connectedAccounts: 6, brands: 2, monthlyCredits: 3500, creditPolicy: 'credits-v2-2026-09-28' },
    studio: { members: 1, connectedAccounts: 3, writingBatches: 0 },
    assist: { members: 1, connectedAccounts: 3, writingBatches: 100 },
    trial: { members: 1, connectedAccounts: 2, writingBatches: 10 },
    starter: { members: 1, connectedAccounts: 3, monthlyCredits: 1000 }
  }[plan],
  catalogState: plan === 'free' || plan === 'creator' ? 'public' : plan === 'starter' ? 'hidden' : 'legacy',
  newCheckoutEnabled: false,
  current: false,
  ...extra
});

const wallet = (extra = {}) => ({
  mode: 'credits',
  availableMilliCredits: 2_140_000,
  heldMilliCredits: 0,
  usedMilliCredits: 1_360_000,
  debtMilliCredits: 0,
  currentPeriodGrantMilliCredits: 3_500_000,
  currentPeriodExpiresAt: NOW + 20 * DAY,
  quoteType: 'spending_limit',
  textOnly: true,
  ...extra
});

function usage(extra = {}) {
  return {
    billingMode: 'free_preview',
    catalogVersion: V2,
    creatorOffer: null,
    freePreview: null,
    credits: null,
    entitlement: { planTermsId: 'free-v1', writingBatchesRemaining: 0, mediaCreditsRemaining: 0, connectedAccounts: 1, members: 1, storageMb: 200, resetsAt: null, source: 'free', version: 1 },
    subscription: null,
    budget: null,
    overage: 'stop',
    ledger: [],
    planTerms: [terms('free-v1', 'free', { current: true }), terms('creator-v1', 'creator')],
    note: '',
    lifecycle: { status: 'free', plan: 'free' },
    billing: { provider: 'stripe', checkoutAvailable: false, portalAvailable: false },
    membership: { role: 'owner' },
    ...extra
  };
}

test('billing mode comes from the server field, never from a price, a batch count or a wallet', () => {
  assert.equal(billingModeOf(usage({ credits: wallet(), entitlement: { writingBatchesRemaining: 10 } })), 'free_preview');
  assert.equal(billingModeOf(usage({ billingMode: 'legacy_allowances', subscription: { priceCents: 5900 } })), 'legacy_allowances');
  assert.equal(billingModeOf(usage({ billingMode: 'managed_credits', credits: null })), 'managed_credits');
  const older = usage();
  delete older.billingMode;
  assert.equal(billingModeOf(older), 'legacy_allowances', 'a response without the field predates v2: only the legacy catalog ever sent it');
  assert.equal(billingModeOf(usage({ billingMode: 'something_new' })), null, 'an unknown mode shows nothing mode-specific');
  assert.equal(billingModeOf(undefined), null);
});

test('credit meter: measured against the period grant, with reset date and no silent overage', () => {
  const meter = creditMeter(wallet(), NOW);
  assert.equal(meter.kind, 'measured');
  assert.equal(meter.available, 2140);
  assert.equal(meter.total, 3500);
  assert.equal(meter.fill, 2140 / 3500);
  assert.equal(meter.warn, false);
  assert.equal(meter.resetsAt, NOW + 20 * DAY);
  assert.equal(meter.expiringSoon, false);
  assert.equal(meter.held, 0);
});

test('credit meter: held credits are shown apart from what is left', () => {
  const meter = creditMeter(wallet({ availableMilliCredits: 2_095_000, heldMilliCredits: 45_000 }), NOW);
  assert.equal(meter.available, 2095);
  assert.equal(meter.held, 45);
});

test('credit meter: amber at 10% or less left; exact 0.1-credit resolution, never rounded up', () => {
  assert.equal(CREDIT_WARN_RATIO, 0.1);
  assert.equal(creditMeter(wallet({ availableMilliCredits: 350_000 }), NOW).warn, true);
  assert.equal(creditMeter(wallet({ availableMilliCredits: 351_000 }), NOW).warn, false);
  assert.equal(creditsFromMilli(47_050), 47);
  assert.equal(creditsFromMilli(3_900), 3.9);
  assert.equal(creditsFromMilli(-5), 0);
});

test('credit meter: an unknown period total shows what is available without inventing a bar', () => {
  const meter = creditMeter(wallet({ currentPeriodGrantMilliCredits: null, currentPeriodExpiresAt: null }), NOW);
  assert.equal(meter.kind, 'no_total');
  assert.equal(meter.reason, 'total_unknown');
  assert.equal(meter.available, 2140);
  assert.equal(meter.resetsAt, null);
  assert.equal(creditMeter(wallet({ availableMilliCredits: 4_000_000 }), NOW).reason, 'above_period_grant');
});

test('credit meter: debt and expiring credits are stated; a missing or malformed wallet is unavailable, never zero', () => {
  assert.equal(creditMeter(wallet({ debtMilliCredits: 12_000 }), NOW).debt, 12);
  const expiring = creditMeter(wallet({ currentPeriodExpiresAt: NOW + 2 * DAY }), NOW);
  assert.equal(expiring.expiringSoon, true);
  assert.equal(creditMeter(wallet({ currentPeriodExpiresAt: NOW + 2 * DAY, availableMilliCredits: 0 }), NOW).expiringSoon, false);
  assert.deepEqual(creditMeter(null, NOW), { kind: 'unavailable' });
  assert.deepEqual(creditMeter(wallet({ availableMilliCredits: Number.NaN }), NOW), { kind: 'unavailable' });
});

test('Free preview lists what is left of each first-value action; unreadable status is not zero', () => {
  assert.equal(freePreviewItems(null), null);
  const items = freePreviewItems({
    postDoctor: { remaining: 1, eligible: true, reason: null },
    genome: { remaining: 0, eligible: false, reason: 'used', maxPosts: 20 }
  });
  assert.deepEqual(items.map((item) => [item.key, item.state, item.remaining]), [['postDoctor', 'ready', 1], ['genome', 'used', 0]]);
  assert.equal(items[1].maxPosts, 20);
  const blocked = freePreviewItems({ postDoctor: { remaining: 1, eligible: false, reason: 'consent_required' }, genome: { remaining: 1, eligible: false, reason: 'funding_unavailable' } });
  assert.deepEqual(blocked.map((item) => [item.state, item.reason]), [['unavailable', 'consent_required'], ['unavailable', 'funding_unavailable']]);
});

test('v2 plan cards: Free and Creator only, current first by price, Creator at this workspace’s own price', () => {
  const data = usage({
    planTerms: [terms('studio-v1', 'studio'), terms('creator-v1', 'creator'), terms('free-v1', 'free', { current: true }), terms('starter-v1', 'starter'), terms('studio-v2', 'studio', { catalogState: 'hidden', priceCents: 14900 })]
  });
  assert.equal(planListKind(data), 'v2');
  const cards = v2PlanCardModels(data, true);
  assert.deepEqual(cards.map((card) => card.terms.id), ['free-v1', 'creator-v1']);
  assert.equal(cards[0].current, true);
  assert.equal(cards[0].priceCents, 0);
  assert.equal(cards[1].priceCents, null, 'no assignment yet: no price is shown, never the experiment');
  const offered = v2PlanCardModels(usage({ creatorOffer: { planTermsId: 'creator-v1', priceVariantId: 'creator-79-v1', amountCents: 7900, currency: 'USD' } }), true);
  assert.equal(offered[1].priceCents, 7900);
  assert.equal(planListKind(usage({ catalogVersion: 'legacy-2026-09' })), 'legacy');
});

test('v2 plan offers: a Choose button only when checkout can work; Free is never bought', () => {
  const open = (extra = {}) =>
    usage({
      creatorOffer: { planTermsId: 'creator-v1', priceVariantId: 'creator-59-v1', amountCents: 5900, currency: 'USD' },
      planTerms: [terms('free-v1', 'free', { current: true }), terms('creator-v1', 'creator', { status: 'active', newCheckoutEnabled: true })],
      billing: { provider: 'stripe', checkoutAvailable: true, portalAvailable: false },
      ...extra
    });
  const offers = (data, owner = true) => v2PlanCardModels(data, owner).map((card) => card.offer);
  assert.deepEqual(offers(open()), ['current', 'checkout']);
  assert.deepEqual(offers(open(), false), ['current', 'owner_only']);
  assert.deepEqual(offers(open({ billing: { provider: 'stripe', checkoutAvailable: false, portalAvailable: false } })), ['current', 'not_open']);
  assert.deepEqual(offers(usage()), ['current', 'not_open'], 'proposed Creator: honest "not open yet", never a dead Choose button');
  assert.deepEqual(offers(open({ creatorOffer: null })), ['current', 'none'], 'no price for this workspace: no checkout, and no claim that checkout is closed');
  const subscriber = open({
    billingMode: 'managed_credits',
    entitlement: { ...usage().entitlement, planTermsId: 'creator-v1', source: 'subscription' },
    subscription: { planTermsId: 'creator-v1', status: 'active', priceCents: 7900, currency: 'USD', priceVariantId: 'creator-79-v1', label: 'Creator', priceStatus: 'active' },
    lifecycle: { status: 'active' },
    creatorOffer: null
  });
  const cards = v2PlanCardModels(subscriber, true);
  assert.deepEqual(cards.map((card) => card.offer), ['none', 'current']);
  assert.equal(cards[1].priceCents, 7900, 'a 79 subscriber sees 79, not the default 59');
  const legacyHolder = open({
    billingMode: 'legacy_allowances',
    entitlement: { ...usage().entitlement, planTermsId: 'studio-v1', source: 'subscription' },
    subscription: { planTermsId: 'studio-v1', status: 'active', priceCents: 1900, currency: 'USD', priceVariantId: null, label: 'Studio', priceStatus: 'active' },
    lifecycle: { status: 'active' },
    planTerms: [terms('free-v1', 'free'), terms('creator-v1', 'creator', { status: 'active', newCheckoutEnabled: true }), terms('studio-v1', 'studio', { current: true })]
  });
  assert.deepEqual(v2PlanCardModels(legacyHolder, true).map((card) => [card.terms.id, card.offer]), [['free-v1', 'none'], ['creator-v1', 'none']]);
});

test('a legacy package is labelled legacy only once v2 sells something else', () => {
  const legacyHolder = (catalogVersion, termsId = 'studio-v1', plan = 'studio') =>
    usage({ billingMode: 'legacy_allowances', catalogVersion, entitlement: { ...usage().entitlement, planTermsId: termsId }, planTerms: [terms(termsId, plan, { current: true })] });
  assert.equal(isLegacyPlanUnderV2(legacyHolder(V2)), true);
  assert.equal(isLegacyPlanUnderV2(legacyHolder('legacy-2026-09')), false);
  assert.equal(isLegacyPlanUnderV2(legacyHolder(V2, 'trial-v1', 'trial')), false, 'a running trial is a trial, not a grandfathered package');
  assert.equal(isLegacyPlanUnderV2(usage()), false);
});

test('work surfaces: v2 never reads writing batches; legacy keeps them', () => {
  assert.deepEqual(writingAllowance({ isLoading: true }), { kind: 'loading' });
  assert.deepEqual(writingAllowance({ isError: true }), { kind: 'unavailable' });
  assert.deepEqual(writingAllowance({ data: usage() }), { kind: 'free' });
  const creator = usage({ billingMode: 'managed_credits', credits: wallet(), entitlement: { ...usage().entitlement, writingBatchesRemaining: 0 } });
  assert.deepEqual(writingAllowance({ data: creator }), { kind: 'credits', available: 2140, resetsAt: NOW + 20 * DAY, debt: 0 });
  assert.deepEqual(writingAllowance({ data: usage({ billingMode: 'managed_credits', credits: null }) }), { kind: 'unavailable' });
  const legacy = usage({ billingMode: 'legacy_allowances', entitlement: { ...usage().entitlement, writingBatchesRemaining: 7, resetsAt: NOW + DAY } });
  assert.deepEqual(writingAllowance({ data: legacy }), { kind: 'batches', remaining: 7, resetsAt: NOW + DAY });
  assert.equal(writingAllowance({ data: { ...legacy, credits: wallet() } }).kind, 'credits', 'a legacy credit pilot spends its wallet, not batches');
});

test('reminders: "Writing allowance used up" only for legacy; credits say credits; Free has none', () => {
  const creator = usage({ billingMode: 'managed_credits', credits: wallet(), entitlement: { ...usage().entitlement, writingBatchesRemaining: 0 } });
  assert.equal(allowanceReminder(creator, NOW), null, 'a Creator with 0 batches and credits left is not blocked');
  assert.equal(allowanceReminder(usage(), NOW), null);
  assert.deepEqual(allowanceReminder(usage({ billingMode: 'legacy_allowances', entitlement: { ...usage().entitlement, writingBatchesRemaining: 0, resetsAt: NOW + 5 * DAY } }), NOW), { kind: 'batches', left: 0, resetsAt: NOW + 5 * DAY });
  assert.equal(allowanceReminder(usage({ billingMode: 'legacy_allowances', entitlement: { ...usage().entitlement, writingBatchesRemaining: 3 } }), NOW), null);
  assert.deepEqual(allowanceReminder({ ...creator, credits: wallet({ availableMilliCredits: 0 }) }, NOW), { kind: 'credits_out', resetsAt: NOW + 20 * DAY });
  assert.deepEqual(allowanceReminder({ ...creator, credits: wallet({ availableMilliCredits: 300_000 }) }, NOW), { kind: 'credits_low', left: 300, resetsAt: NOW + 20 * DAY });
  assert.deepEqual(allowanceReminder({ ...creator, credits: wallet({ debtMilliCredits: 5_000 }) }, NOW), { kind: 'credits_debt', debt: 5 });
});

test('model cost classes follow what the workspace spends', () => {
  assert.equal(costClassKey('paid', { kind: 'batches', remaining: 3, resetsAt: null }), 'batches');
  assert.equal(costClassKey('paid', { kind: 'credits', available: 1, resetsAt: null, debt: 0 }), 'credits');
  assert.equal(costClassKey('paid', { kind: 'free' }), 'free_plan');
  assert.equal(costClassKey('paid', { kind: 'loading' }), 'paid');
  assert.equal(costClassKey('none', { kind: 'free' }), 'none');
  assert.equal(costClassKey('subscription', { kind: 'credits', available: 1, resetsAt: null, debt: 0 }), 'subscription');
  assert.equal(costClassKey(undefined, { kind: 'free' }), 'unreported');
});

test('in-app v2 copy exists in English and Traditional Chinese with the same shape', () => {
  const shape = (value) =>
    Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, typeof entry === 'function' ? 'fn' : typeof entry === 'object' && entry !== null ? shape(entry) : typeof entry]));
  assert.deepEqual(shape(BILLING_COPY['zh-Hant']), shape(BILLING_COPY.en));
  for (const locale of ['en', 'zh-Hant']) {
    const text = JSON.stringify(BILLING_COPY[locale], (key, value) => (typeof value === 'function' ? value('1', '2', '3') : value));
    assert.doesNotMatch(text, /writing batch|批次/i, `${locale} v2 copy never mentions writing batches`);
    assert.match(text, locale === 'en' ? /No silent overage/ : /不會悄悄超額收費/);
  }
  for (const [tag, locale] of [[undefined, 'en'], ['en-GB', 'en'], ['zh-Hant', 'zh-Hant'], ['zh-Hant-HK', 'zh-Hant'], ['zh-TW', 'zh-Hant'], ['zh-HK', 'zh-Hant'], ['yue', 'zh-Hant'], ['zh-Hans', 'en'], ['zh', 'en']]) {
    assert.equal(copyLocale(tag), locale, String(tag));
  }
  assert.equal(billingCopy('zh-Hant').creditMeter.title, BILLING_COPY['zh-Hant'].creditMeter.title);
});
