const { test } = require('node:test');
const assert = require('node:assert/strict');
const { environment } = require('./pricing-v2-billing-loader.cjs');
const { NOW, creator, balance, usage, legacy } = require('./pricing-v2-billing-fixtures.cjs');
const redirect = { stateFor: () => 'idle', errorFor: () => null, busy: false, openPortal() {}, startCheckout() {} };
const render = data => environment(data).render('features/billing/billing-view.tsx', 'BillingView');
const model = environment(usage()).load('features/billing/billing-model.ts');

test('gross period grant, held, debt and lifetime usage remain independent; no invented period percentage', () => {
  assert.equal(typeof model.managedCreditState, 'function');
  const state = model.managedCreditState(balance({ debtMilliCredits: 90000 }));
  assert.equal(state.available, 4800000); assert.equal(state.held, 200000);
  assert.equal(state.lifetimeUsed, 7200000); assert.equal(state.periodGrant, 3500000);
  assert.equal(state.debt, 90000); assert.equal(state.periodExpiresAt, NOW + 86400);
  assert.equal(state.purchasedLots[0].expiresAt, null);
  assert.equal(state.fill, undefined); assert.equal(state.periodUsed, undefined);
});
test('unknown period totals stay null, while actual absolute balances remain readable', () => {
  assert.equal(typeof model.managedCreditState, 'function');
  assert.equal(model.managedCreditState(balance({ currentPeriodGrantMilliCredits: null, currentPeriodExpiresAt: null })).periodGrant, null);
  assert.equal(model.managedCreditState(null).kind, 'unavailable');
});
test('managed rendering shows held, lifetime, gross grant, actual expiry and no legacy meters or percentage', () => {
  const html = render(usage());
  assert.match(html, /Managed credits/); assert.match(html, /Held/); assert.match(html, /Lifetime used/);
  assert.match(html, /Current-period grant/); assert.match(html, /3,500/); assert.match(html, /expire/);
  assert.match(html, /No silent overage/); assert.match(html, /Purchased credits/); assert.match(html, /Expiry unavailable/);
  assert.doesNotMatch(html, /AI writing batches|Media credits/);
  const credits = environment(usage()).render('features/billing/credit-balance.tsx', 'CreditBalance', { balance: balance() });
  assert.doesNotMatch(credits, /role="progressbar"/);
});
test('managed unknown wallet, including verified exemption, never falls to legacy counters', () => {
  for (const aiUsageExempt of [false, true]) {
    const html = render(usage('managed_credits', { credits: null, aiUsageExempt }));
    assert.match(html, /Managed credits/); assert.doesNotMatch(html, /AI writing batches|Media credits|0\s*\/\s*0/);
  }
});
test('Free shows actual remaining and eligibility; ended Creator is history, not the current plan', () => {
  const data = usage('free_preview'); data.lifecycle.status = 'expired';
  data.entitlement = { ...data.entitlement, plan: 'free', planTermsId: 'free-v1' };
  const html = render(data);
  assert.match(html, /Free preview/); assert.match(html, /Post Doctor/); assert.match(html, /Used/);
  assert.match(html, /Genome/); assert.match(html, /1 preview remaining/); assert.match(html, /Preview unavailable/);
  assert.match(html, /Previous plan/); assert.match(html, /\$49/);
  assert.doesNotMatch(html, /AI writing batches|Media credits|Cloud credits|aria-label="Managed credits"/);
  const preview = environment(data).render('features/billing/free-preview.tsx', 'FreePreview', { preview: data.freePreview });
  assert.doesNotMatch(preview, /role="progressbar"|0\s*\/\s*0/);
});
test('Free eligible preview uses persisted action count and actual recent-post limit', () => {
  const data = usage('free_preview', { subscription: null });
  data.freePreview.postDoctor = { remaining: 1, eligible: true, reason: null };
  const html = render(data); assert.match(html, /Available/); assert.match(html, /20/);
});
test('legacy 19 and 39 preserve actual meters and receipt even with an incidental wallet', () => {
  for (const price of [1900, 3900]) {
    const data = legacy(price); data.credits = balance();
    const html = render(data);
    assert.match(html, /Legacy/); assert.match(html, /AI writing batches/); assert.match(html, /12/);
    assert.match(html, /Media credits/); assert.match(html, new RegExp(`\\$${price / 100}`));
    assert.doesNotMatch(html, /aria-label="Managed credits"|Choose Studio|Choose Assist|Switch in Manage plan/);
  }
});
test('assigned Creator 49/59/79 is one offer with identical 3500; default price is never substituted', () => {
  for (const price of [4900, 5900, 7900]) {
    const data = usage('free_preview', { subscription: null, planTerms: [creator(price)] });
    const html = environment(data).render('features/billing/plans.tsx', 'Plans', { usage: data, isOwner: true, redirect });
    assert.match(html, new RegExp(`\\$${price / 100}`)); assert.match(html, /3,500/);
    assert.doesNotMatch(html, /AI writing batches|Media credits|Choose Creator/);
  }
});
test('every source gate is required; hidden and legacy rows cannot be offered or switched', () => {
  const active = creator(5900, { status: 'active', checkoutAvailable: true, newCheckoutEnabled: true });
  const input = { terms: active, currentTermsId: 'free-v1', lifecycleStatus: 'active', checkoutAvailable: true, isOwner: true };
  // A Free lifecycle can be active with no open paid subscription.
  input.lifecycleStatus = 'free';
  assert.equal(model.planOffer(input), 'checkout');
  for (const patch of [{ status: 'proposed' }, { checkoutAvailable: false }, { newCheckoutEnabled: false }, { catalogState: 'hidden' }, { catalogState: 'legacy' }, { priceVariantId: null }]) {
    assert.equal(model.planOffer({ ...input, terms: { ...active, ...patch } }), 'not_available', JSON.stringify(patch));
  }
  assert.equal(model.planOffer({ ...input, checkoutAvailable: false }), 'not_available');
  assert.equal(model.planOffer({ ...input, isOwner: false }), 'owner_only');
});
test('owner provider USD diagnostics are behind a separate advanced disclosure; members get none', () => {
  const html = render(usage()); assert.match(html, /<details[^>]*[\s\S]*Advanced usage/);
  const member = usage(); member.membership.permissions = ['read']; member.membership.role = 'viewer';
  const hidden = render(member); assert.doesNotMatch(hidden, /Advanced usage|AI spend this|Estimated|\$1\.20/);
});
test('unavailable, empty, or failed pack catalog never exposes stale pack checkout', () => {
  const packs = [{ id: 'synthetic-pack', label: 'Prepared', amountCents: 1500, currency: 'usd', milliCredits: 1000000 }];
  for (const [response, error] of [[{ available: false, packs }, false], [{ available: true, packs: [] }, false], [{ available: true, packs }, true]]) {
    const html = environment(usage(), response, error).render('features/billing/credit-packs.tsx', 'CreditPacks');
    assert.doesNotMatch(html, /Add credits|1,000 credits|Confirm purchase/);
  }
});
