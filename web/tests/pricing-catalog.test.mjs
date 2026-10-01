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
const STALE_V2 = [/writing batch/i, /\$19\b/, /\$39\b/, /US\$19/, /US\$39/, /\btrial\b/i, /Studio Assist/i, /\bStudio\b/, /\bStarter\b/, /media credit/i, /two plans/i];

test('AC05: the web v2 catalog equals the contract fixture the database is tested against', () => {
  assert.deepStrictEqual(V2_CATALOG, FIXTURE);
});

test('AC01: v2 sells Free and Creator only; Creator defaults to US$59 with 3,500 managed credits; no top-ups', () => {
  assert.deepEqual(V2_CATALOG.plans.map((plan) => plan.id), ['free-v1', 'creator-v1']);
  const free = catalogPlan('free');
  const creator = catalogPlan('creator');
  assert.equal(free.priceCents, 0);
  assert.equal(catalogLimit(free, 'monthlyCredits'), 0);
  assert.equal(creator.priceCents, 5900);
  assert.equal(catalogLimit(creator, 'monthlyCredits'), 3500);
  assert.equal(usdText(creator.priceCents), 'US$59');
  assert.equal(V2_CATALOG.creditsPerUsd, 300);
  assert.equal(V2_CATALOG.topUps.available, false);
  for (const hidden of ['starter', 'studio', 'assist', 'trial']) assert.equal(catalogPlan(hidden), undefined, `${hidden} is never for sale under v2`);
});

test('the build-time switch defaults to legacy; only "v2" turns Pricing v2 on', () => {
  for (const value of [undefined, null, '', 'legacy', 'v1', 'v3', 'true']) assert.equal(pricingCatalogId(value), 'legacy');
  for (const value of ['v2', ' v2 ', 'V2']) assert.equal(pricingCatalogId(value), 'v2');
  assert.equal(PRICING_CATALOG, pricingCatalogId(process.env.NEXT_PUBLIC_PRICING_CATALOG));
});

test('v2 public cards: outcomes and numbers from the catalog, never legacy sales language', () => {
  const cards = v2PlanCards();
  assert.deepEqual(cards.map((card) => card.name), ['Free', 'Creator']);
  const [free, creator] = cards;
  assert.equal(free.interval, null);
  assert.equal(creator.interval, 'month');
  assert.ok(free.highlights.includes('One Post Doctor check on a draft of yours'));
  assert.ok(free.highlights.includes('One analysis of up to 20 recent posts'));
  assert.ok(free.highlights.includes('1 connected account · 1 brand · 1 seat'));
  assert.ok(creator.highlights.includes('3,500 managed AI credits every month'));
  assert.ok(creator.highlights.includes('Up to 6 connected accounts · up to 2 brands · 1 seat'));
  assert.ok(creator.highlights.some((line) => /no silent overage/i.test(line)));
  assert.ok(creator.highlights.some((line) => /no rollover/i.test(line)));
  const text = JSON.stringify(cards);
  for (const re of STALE_V2) assert.doesNotMatch(text, re);
  assert.doesNotMatch(text, /storage|MB|GB/i, 'storage is not a v2 pricing headline');
});

test('v2 card actions follow checkout: no dead buy button before Creator checkout opens', () => {
  const [free, creator] = v2PlanCards();
  const freeAction = v2CardAction(free, '/auth/sign-up');
  assert.deepEqual([freeAction.label, freeAction.href], ['Start free', '/auth/sign-up']);
  const closed = v2CardAction(creator, '/auth/sign-up');
  assert.equal(creator.checkout, 'not_yet_available');
  assert.equal(closed.label, 'Start free');
  assert.equal(closed.href, '/auth/sign-up');
  assert.match(closed.note, /isn’t open yet/);
  const open = v2CardAction({ ...creator, checkout: 'available' }, '/auth/sign-up');
  assert.equal(open.label, 'Get Creator');
  assert.equal(open.href, '/auth/sign-up?next=%2Fapp%2Faccount%2Fbilling%23plans');
});

test('JSON-LD lists only offers a customer can buy right now', () => {
  assert.deepEqual(jsonLdOffers('v2'), [], 'seeded Creator is not purchasable yet, and Free is not a purchase');
  const activated = { ...V2_CATALOG, plans: V2_CATALOG.plans.map((plan) => (plan.plan === 'creator' ? { ...plan, checkout: 'available' } : plan)) };
  assert.deepEqual(jsonLdOffers('v2', activated), [{ '@type': 'Offer', name: 'Creator', price: '59.00', priceCurrency: 'USD', category: 'subscription' }]);
  assert.deepEqual(jsonLdOffers('legacy'), [], 'legacy keeps today’s rule: only active terms, none yet');
});

test('legacy catalog is unchanged: Studio US$19, Studio Assist US$39 and the 14-day trial', () => {
  assert.deepEqual(plans.map((plan) => [plan.id, plan.planTermsId, plan.priceCents, plan.status]), [
    ['studio', 'studio-v1', 1900, 'proposed'],
    ['assist', 'assist-v1', 3900, 'proposed']
  ]);
  assert.deepEqual({ ...TRIAL }, { days: 14, connectedAccounts: 2, writingBatches: 10, mediaCredits: 1, storageMb: 200, cardRequired: false, autoConvert: false });
});
