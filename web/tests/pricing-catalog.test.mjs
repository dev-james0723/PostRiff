/**
 * Pricing v2 public catalog (PRD R-COM-01/04, AC01/AC05; spec §12.1, §13.1). The web catalog module must equal the
 * contract fixture that a disposable-PostgreSQL test holds the database to (tests/phase2/postgres_pricing_catalog_contract.py),
 * so database ↔ fixture ↔ public pages agree. Legacy stays byte-for-byte today's catalog until v2 is switched on.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  PRICING_CATALOG,
  TRIAL,
  V2_CATALOG,
  catalogLimit,
  catalogPlan,
  jsonLdOffers,
  plans,
  pricingCatalogId,
  usdText,
  v2CardAction,
  v2PlanCards
} from '../src/config/plans.ts';

const FIXTURE = JSON.parse(readFileSync(new URL('../../docs/design/rafii-product-growth/contracts/pricing-catalog-v2.json', import.meta.url), 'utf8'));
const STALE_V2 = [/writing batch/i, /\$19\b/, /\$39\b/, /US\$19/, /US\$39/, /\btrial\b/i, /Studio Assist/i, /media credit/i, /two plans/i];

test('AC05: the web v2 catalog equals the contract fixture the database is tested against', () => {
  assert.deepStrictEqual(V2_CATALOG, FIXTURE);
});

test('AC01: v2 presents Free and proposed Starter, Creator and Studio; Creator defaults to US$59 with 3,500 managed credits; no top-ups', () => {
  assert.deepEqual(V2_CATALOG.plans.map((plan) => plan.id), ['free-v1', 'starter-v1', 'creator-v1', 'studio-v2']);
  const free = catalogPlan('free');
  const creator = catalogPlan('creator');
  assert.equal(free.priceCents, 0);
  assert.equal(catalogLimit(free, 'monthlyCredits'), 0);
  assert.equal(creator.priceCents, 5900);
  assert.equal(catalogLimit(creator, 'monthlyCredits'), 3500);
  assert.equal(usdText(creator.priceCents), 'US$59');
  assert.equal(V2_CATALOG.creditsPerUsd, 300);
  assert.equal(V2_CATALOG.topUps.available, false);
  for (const hidden of ['assist', 'trial']) assert.equal(catalogPlan(hidden), undefined, `${hidden} is never for sale under v2`);
});

test('the public selector always keeps Free and Creator, including OFF/legacy rollback', () => {
  for (const value of [undefined, null, '', 'legacy', 'v1', 'v3', 'true']) assert.equal(pricingCatalogId(value), 'v2');
  for (const value of ['v2', ' v2 ', 'V2']) assert.equal(pricingCatalogId(value), 'v2');
  assert.equal(PRICING_CATALOG, pricingCatalogId(process.env.NEXT_PUBLIC_PRICING_CATALOG));
});

test('v2 public cards: outcomes and numbers from the catalog, never legacy sales language', () => {
  const cards = v2PlanCards();
  assert.deepEqual(cards.map((card) => card.name), ['Free', 'Starter', 'Creator', 'Studio']);
  const [free, starter, creator, studio] = cards;
  assert.deepEqual([starter.priceCents, starter.monthlyCredits, studio.priceCents, studio.monthlyCredits], [2900, 1000, 14900, 8000]);
  for (const paid of [starter, studio]) {
    assert.equal(v2CardAction(paid, '/auth/sign-up').href, null);
    assert.ok(paid.highlights.includes(`${paid.monthlyCredits.toLocaleString('en-US')} managed AI credits every month`));
  }
  assert.equal(free.interval, null);
  assert.equal(creator.interval, 'month');
  assert.ok(free.highlights.includes('One Post Doctor check on a draft of yours, when available'));
  assert.ok(free.highlights.includes('One analysis of up to 20 recent posts, when available'));
  assert.ok(free.highlights.includes('1 connected account · 1 brand · 1 seat'));
  assert.ok(creator.highlights.includes('3,500 managed AI credits every month'));
  assert.ok(creator.highlights.includes('Up to 6 connected accounts · up to 2 brands · 1 seat'));
  assert.ok(creator.highlights.some((line) => /no silent overage/i.test(line)));
  assert.ok(creator.highlights.some((line) => /no rollover/i.test(line)));
  const text = JSON.stringify(cards);
  for (const re of STALE_V2) assert.doesNotMatch(text, re);
  assert.doesNotMatch(text, /storage|MB|GB/i, 'storage is not a v2 pricing headline');
});

test('v2 card actions stay Free-first; client checkout flags cannot authorize Creator purchase', () => {
  const [free, , creator] = v2PlanCards();
  const freeAction = v2CardAction(free, '/auth/sign-up');
  assert.deepEqual([freeAction.label, freeAction.href], ['Start free', '/auth/sign-up']);
  const closed = v2CardAction(creator, '/auth/sign-up');
  assert.equal(creator.checkout, 'not_yet_available');
  assert.equal(closed.label, 'Creator unavailable');
  assert.equal(closed.href, null);
  assert.match(closed.note, /proposed/);
  assert.match(closed.note, /not available for purchase/);
  const open = v2CardAction({ ...creator, checkout: 'available' }, '/auth/sign-up');
  assert.equal(open.label, 'Creator unavailable');
  assert.equal(open.href, null);
  assert.match(open.note, /not available for purchase/);
});

test('JSON-LD includes only Free under v2, even if a client marks Creator available', () => {
  const freeOffer = [{ '@type': 'Offer', name: 'Free', price: '0.00', priceCurrency: 'USD', category: 'subscription' }];
  assert.deepEqual(jsonLdOffers('v2'), freeOffer, 'proposed Creator has no paid offer');
  const activated = { ...V2_CATALOG, plans: V2_CATALOG.plans.map((plan) => (plan.plan === 'creator' ? { ...plan, checkout: 'available' } : plan)) };
  assert.deepEqual(jsonLdOffers('v2', activated), freeOffer);
  assert.doesNotMatch(JSON.stringify(jsonLdOffers('v2', activated)), /Creator|InStock|PreOrder|availability|validFrom/);
  assert.deepEqual(jsonLdOffers('legacy'), freeOffer, 'legacy public selector cannot restore legacy sales');
});

test('legacy account reference data remains unchanged and is not the public new-sale catalog', () => {
  assert.deepEqual(plans.map((plan) => [plan.id, plan.planTermsId, plan.priceCents, plan.status]), [
    ['studio', 'studio-v1', 1900, 'proposed'],
    ['assist', 'assist-v1', 3900, 'proposed']
  ]);
  assert.deepEqual({ ...TRIAL }, { days: 14, connectedAccounts: 2, writingBatches: 10, mediaCredits: 1, storageMb: 200, cardRequired: false, autoConvert: false });
});
