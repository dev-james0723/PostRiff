const {test}=require('node:test');
const assert=require('node:assert/strict');
const {environment}=require('./pricing-v2-billing-loader.cjs');
const {usage}=require('./pricing-v2-billing-fixtures.cjs');

function customerWallet(extra={}) {
  const data=usage();delete data.credits.lots;delete data.credits.purchasedCredits;
  data.credits={...data.credits,...extra};return data;
}
function render(data) {
  let html;assert.doesNotThrow(()=>{html=environment(data).render('features/billing/billing-view.tsx','BillingView');});
  return html;
}
test('R6 actual customer API wallet without private lots renders balances and unknown purchase detail',()=>{
  const data=customerWallet();const html=render(data);
  assert.match(html,/Managed credits/);assert.match(html,/Lifetime used/);assert.match(html,/Current-period grant/);
  assert.match(html,/Purchased credit details unavailable/);
});
test('R6 safe purchased-credit facts render available and held without raw lot identifiers or invented expiry',()=>{
  const html=render(customerWallet({purchasedCredits:[{available:2000000,held:1000,expiresAt:null}]}));
  assert.match(html,/Purchased credits/);assert.match(html,/2,000 available/);assert.match(html,/1 held/);
  assert.match(html,/Expiry unavailable/);assert.doesNotMatch(html,/purchase-one|grantId|12 months/);
});
test('R6 empty verified purchase projection and unknown projection remain different',()=>{
  const empty=render(customerWallet({purchasedCredits:[]}));
  assert.doesNotMatch(empty,/Purchased credit details unavailable|<h3[^>]*>Purchased credits/);
  assert.match(render(customerWallet({purchasedCredits:null})),/Purchased credit details unavailable/);
});
