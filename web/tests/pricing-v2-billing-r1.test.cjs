const { test } = require('node:test');
const assert = require('node:assert/strict');
const { environment } = require('./pricing-v2-billing-loader.cjs');
const { usage, creator } = require('./pricing-v2-billing-fixtures.cjs');
const packs = { available: true, packs: [{ id: 'r1-synthetic-pack', label: 'Synthetic active row', amountCents: 1500, currency: 'usd', milliCredits: 1000000 }] };
const failed = { isError: true, isSuccess: false, error: new Error('Synthetic failed usage refresh') };
const recovered = { isError: false, isSuccess: true, error: null, dataUpdatedAt: 2 };
function free(owner = true) {
  const data = usage('free_preview', { subscription: null, lifecycle: { status: 'free' }, billing: { provider: 'fixture', checkoutAvailable: true, portalAvailable: false }, planTerms: [creator(7900, { status: 'active', newCheckoutEnabled: true, checkoutAvailable: true })] });
  data.entitlement.plan = 'free'; data.entitlement.planTermsId = 'free-v1';
  if (!owner) data.membership = { ...data.membership, role: 'viewer', permissions: ['read'] };
  return data;
}
function activeButtons(html, text) {
  return [...html.matchAll(/(<button\b[^>]*>)([\s\S]*?)<\/button>/g)].filter(row => row[2].replace(/<[^>]*>/g, '').includes(text) && !/\bdisabled(?:=|\s|>)/.test(row[1])).length;
}
const render = env => env.render('features/billing/billing-view.tsx', 'BillingView');
test('R1 owner cached Creator response loses both purchase entry points after failed refresh', () => {
  const env = environment(free());
  assert.equal(activeButtons(render(env), 'Choose Creator'), 1);
  env.setUsageRead(failed); const stale = render(env);
  assert.match(stale, /Couldn’t refresh/); assert.match(stale, /\$79/);
  assert.equal(activeButtons(stale, 'Choose Creator'), 0);
  assert.doesNotMatch(stale, /href="#plans"/);
});
test('R1 owner cached managed response loses pack selection after failed Usage refresh', () => {
  const env = environment(usage(), packs);
  assert.equal(activeButtons(render(env), '1,000 credits'), 1);
  env.setUsageRead(failed); const stale = render(env);
  assert.match(stale, /Couldn’t refresh/); assert.match(stale, /Managed credits/);
  assert.equal(activeButtons(stale, '1,000 credits'), 0);
  assert.doesNotMatch(stale, /Confirm purchase/);
});
test('R1 non-error and successful recovery preserve eligible owner plan checkout', () => {
  const env = environment(free(), packs, false, { ...failed });
  env.setUsageRead(recovered);
  assert.equal(activeButtons(render(env), 'Choose Creator'), 1);
  assert.match(render(env), /href="#plans"/);
});
test('R1 recovery permits owner packs only with a successful available pack read', () => {
  const env = environment(usage(), packs, false, { ...failed }); env.setUsageRead(recovered);
  assert.equal(activeButtons(render(env), '1,000 credits'), 1);
  const packError = environment(usage(), packs, true, { ...recovered });
  assert.equal(activeButtons(render(packError), '1,000 credits'), 0);
});
test('R1 current reads and recovery never bypass owner gates for either purchase path', () => {
  const plans = environment(free(false));
  for (const read of [recovered, failed, recovered]) { plans.setUsageRead(read); assert.equal(activeButtons(render(plans), 'Choose Creator'), 0); assert.doesNotMatch(render(plans), /href="#plans"/); }
  const data = usage(); data.membership = { ...data.membership, role: 'viewer', permissions: ['read'] };
  const env = environment(data, packs);
  for (const read of [recovered, failed, recovered]) { env.setUsageRead(read); assert.equal(activeButtons(render(env), '1,000 credits'), 0); }
});
