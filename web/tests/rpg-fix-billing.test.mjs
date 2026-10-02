/**
 * Product Growth v2 fix pass F1 (billing): truthful plan offers after rollback and for ended legacy plans, Creator
 * never sold while credits can't be spent, zh-Hant v2 plan cards, the plan-aware image toggle (D-026) and the Radar
 * daily-watch copy on credit plans.
 *
 *   node --test web/tests/rpg-fix-billing.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  IMAGE_CREDITS_UNAVAILABLE,
  IMAGE_FREE_UNAVAILABLE,
  checkoutReasonOf,
  imageToggle,
  isLegacyPlanUnderV2,
  legacyPlanEnded,
  v2PlanCardModels
} from '../src/lib/billing/mode.ts';
import { BILLING_COPY } from '../src/lib/billing/mode-copy.ts';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const WEB = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(WEB, 'src');
const read = (path) => readFileSync(join(SRC, path), 'utf8');

/** A stand-in for any module a file imports but these checks never call (components, hooks, icons, styles). */
const STUB = new Proxy(function stub() {}, { get: (_target, key) => (key === '__esModule' ? false : STUB), apply: () => STUB });

/** Load a TypeScript module the way the app sees it; `stub(spec)` may replace an import the checks never call. */
function load(file, stub = () => false, cache = new Map()) {
  if (cache.has(file)) return cache.get(file).exports;
  const out = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023, jsx: ts.JsxEmit.ReactJSX } });
  const mod = { exports: {} };
  cache.set(file, mod);
  const local = (spec) => {
    if (spec.endsWith('.css') || stub(spec)) return STUB;
    if (!spec.startsWith('@/') && !spec.startsWith('.')) return require(spec);
    const base = spec.startsWith('@/') ? join(SRC, spec.slice(2)) : join(dirname(file), spec);
    for (const candidate of [`${base}.ts`, `${base}.tsx`, join(base, 'index.ts')]) {
      try {
        if (statSync(candidate).isFile()) return load(candidate, stub, cache);
      } catch {}
    }
    throw new Error(`Cannot resolve ${spec} from ${file}`);
  };
  new Function('require', 'module', 'exports', out.outputText)(local, mod, mod.exports);
  return mod.exports;
}

const V2 = 'pricing-v2-2026-09-28';
const terms = (id, plan, extra = {}) => ({
  id,
  plan,
  version: 1,
  label: { free: 'Free', creator: 'Creator', studio: 'Studio' }[plan],
  priceCents: { free: 0, creator: 5900, studio: 1900 }[plan],
  currency: 'USD',
  status: 'active',
  priceLabel: 'active',
  entitlements: {},
  catalogState: plan === 'studio' ? 'legacy' : 'public',
  newCheckoutEnabled: plan === 'creator',
  current: false,
  ...extra
});
const usage = (extra = {}) => ({
  billingMode: 'free_preview',
  catalogVersion: V2,
  creatorOffer: { planTermsId: 'creator-v1', priceVariantId: 'creator-59-v1', amountCents: 5900, currency: 'USD' },
  entitlement: { planTermsId: 'free-v1', writingBatchesRemaining: 0, mediaCreditsRemaining: 0, resetsAt: null, source: 'free' },
  subscription: null,
  planTerms: [terms('free-v1', 'free', { current: true }), terms('creator-v1', 'creator')],
  lifecycle: { status: 'free' },
  billing: { provider: 'stripe', checkoutAvailable: true, portalAvailable: false, checkoutReason: null },
  ...extra
});

test('a closed Creator card says why: credits switched off is not "checkout isn’t open"', () => {
  const offers = (reason) =>
    v2PlanCardModels(usage({ billing: { provider: 'stripe', checkoutAvailable: false, portalAvailable: false, checkoutReason: reason } }), true).map((card) => [card.offer, card.reason]);
  assert.deepEqual(offers('credits_unavailable'), [['current', null], ['not_open', 'credits_off']]);
  assert.deepEqual(offers('credit_policy_inactive'), [['current', null], ['not_open', 'credits_off']]);
  assert.deepEqual(offers('not_for_sale'), [['current', null], ['not_open', 'not_open']]);
  assert.deepEqual(offers(undefined), [['current', null], ['not_open', 'not_open']], 'an older server without a reason');
  assert.deepEqual(v2PlanCardModels(usage(), true).map((card) => [card.offer, card.reason]), [['current', null], ['checkout', null]]);
  assert.equal(checkoutReasonOf({ billing: { checkoutReason: 'credits_unavailable' } }), 'credits_unavailable');
  assert.equal(checkoutReasonOf({ billing: undefined }), null);
  for (const locale of ['en', 'zh-Hant']) assert.match(BILLING_COPY[locale].plans.creditsOff('Creator'), /Creator/);
  const view = read('features/billing/plans.tsx');
  assert.match(view, /reason === 'credits_off' \? copy\.creditsOff\(terms\.label\) : copy\.notOpen/);
});

test('an ended legacy plan is not "kept for you"; an open one still is', () => {
  const holder = (status) =>
    usage({
      billingMode: 'legacy_allowances',
      creatorOffer: null,
      entitlement: { ...usage().entitlement, planTermsId: 'studio-v1', source: 'subscription' },
      planTerms: [terms('free-v1', 'free'), terms('creator-v1', 'creator'), terms('studio-v1', 'studio', { current: true })],
      lifecycle: { status }
    });
  assert.equal(isLegacyPlanUnderV2(holder('active')), true);
  assert.equal(legacyPlanEnded(holder('active')), false);
  for (const status of ['cancelled', 'expired']) {
    assert.equal(isLegacyPlanUnderV2(holder(status)), false, status);
    assert.equal(legacyPlanEnded(holder(status)), true, status);
  }
  // No price of its own yet: no Choose button, and no claim that checkout is closed when the server says it is open.
  assert.deepEqual(v2PlanCardModels(holder('cancelled'), true).map((card) => card.offer), ['none', 'none']);
  const card = read('features/billing/plan-card.tsx');
  assert.match(card, /legacyEnded && <p[^>]*>\{canChoose && isOwner \? v2Copy\.legacyEndedChoose : v2Copy\.legacyEndedNote\}/);
  for (const locale of ['en', 'zh-Hant']) {
    assert.doesNotMatch(BILLING_COPY[locale].summary.legacyEndedNote, /kept|保留：價格/i);
  }
});

test('rollback (v2 off): Free is never a Choose button and the summary does not promise Creator', () => {
  const model = load(join(SRC, 'features/billing/billing-model.ts'));
  const offer = (termsRow, extra = {}) =>
    model.planOffer({ terms: termsRow, currentTermsId: 'free-v1', lifecycleStatus: 'cancelled', checkoutAvailable: true, isOwner: true, ...extra });
  assert.equal(offer({ id: 'free-v1', plan: 'free', status: 'active' }), 'current', 'the Free workspace is on Free');
  assert.equal(offer({ id: 'free-v1', plan: 'free', status: 'active' }, { currentTermsId: 'studio-v1' }), 'not_available', 'Free is never bought');
  assert.equal(offer({ id: 'studio-v1', plan: 'studio', status: 'active' }), 'checkout', 'a legacy package can still be bought');
  const card = read('features/billing/plan-card.tsx');
  assert.match(card, /actionLabel: canChoose && isOwner \? \(v2List \? v2Copy\.seeCreator : v2Copy\.seePlans\) : null/);
  assert.equal(BILLING_COPY.en.summary.seePlans, 'See plans');
  assert.equal(BILLING_COPY['zh-Hant'].summary.seePlans, '查看方案');
  const plans = read('features/billing/plans.tsx');
  assert.match(plans, /terms\.plan === 'free' \? '' : ' \/ month'/, 'the legacy list shows Free without a monthly price');
});

test('zh-Hant v2 plan cards carry no English strings', () => {
  const plans = read('features/billing/plans.tsx');
  const v2 = plans.slice(plans.indexOf('function V2Plans'), plans.indexOf('export function Plans'));
  for (const english of ['>Plans<', 'Only the owner can change plans.', '<Badge>Current</Badge>', "loadingText='Opening checkout…'", "errorText='Try again'", "'Not included'", 'checkoutNote(']) {
    assert.ok(!v2.includes(english), `V2Plans still hard-codes ${english}`);
  }
  for (const key of ['heading', 'ownerOnly', 'current', 'notIncluded', 'opening', 'tryAgain', 'stripeNote']) {
    assert.match(v2, new RegExp(`copy\\.${key}`), key);
    assert.doesNotMatch(BILLING_COPY['zh-Hant'].plans[key].replace('Stripe', ''), /[A-Za-z]{3,}/, `zh-Hant ${key} is translated`);
  }
  const summary = load(join(SRC, 'features/billing/billing-copy.ts'));
  const words = BILLING_COPY['zh-Hant'].planSummary;
  const renews = summary.planSummary({ timeline: { kind: 'renews', at: 1_800_000_000 }, planLabel: 'Creator', trial: false, status: 'active', isOwner: true, portalAvailable: true, checkoutAvailable: false }, words);
  assert.equal(renews.actionLabel, '管理方案');
  assert.match(renews.line, /續訂$/);
  const failed = summary.planSummary({ timeline: { kind: 'grace', until: null }, planLabel: 'Creator', trial: false, status: 'past_due', isOwner: true, portalAvailable: true, checkoutAvailable: false }, words);
  assert.deepEqual([failed.badge, failed.line, failed.actionLabel], ['付款失敗', '請更新付款方式', '更新付款資料']);
  const english = summary.planSummary({ timeline: { kind: 'trial_left', endsAt: 1_800_000_000, daysLeft: 3 }, planLabel: null, trial: true, status: 'trial', isOwner: false, portalAvailable: false, checkoutAvailable: false });
  assert.equal(english.line, '3 days left', 'legacy words are unchanged by default');
  assert.match(read('features/billing/plan-card.tsx'), /mode === 'managed_credits' \? copy\.planSummary : billingCopy\('en'\)\.planSummary/);
});

test('the image toggle follows the plan, never the catalog’s legacy media-credit wording (D-026)', () => {
  const capability = { available: true, detail: 'Uses one managed media credit and the approved image budget, independently of the selected writing model or local CLI.' };
  assert.deepEqual(imageToggle(capability, { billingMode: 'managed_credits', credits: { availableMilliCredits: 1 } }), { available: false, detail: IMAGE_CREDITS_UNAVAILABLE });
  assert.deepEqual(imageToggle(capability, { billingMode: 'legacy_allowances', credits: { availableMilliCredits: 1 } }), { available: false, detail: IMAGE_CREDITS_UNAVAILABLE }, 'a legacy credit pilot is refused too');
  assert.deepEqual(imageToggle(capability, { billingMode: 'free_preview', credits: null }), { available: false, detail: IMAGE_FREE_UNAVAILABLE });
  assert.deepEqual(imageToggle(capability, { billingMode: 'legacy_allowances', credits: null }), { available: true, detail: capability.detail });
  assert.deepEqual(imageToggle(capability, {}), { available: true, detail: capability.detail }, 'no billingMode field: a legacy response');
  assert.equal(imageToggle(capability, undefined, true).available, false, 'waits while the plan loads');
  const unknown = imageToggle(capability, undefined, false);
  assert.equal(unknown.available, true, 'the server still decides when the plan cannot be read');
  assert.doesNotMatch(unknown.detail, /credit/i, 'and nothing claims a cost');
  assert.deepEqual(imageToggle({ available: false, detail: 'Configure the image route.' }, { billingMode: 'legacy_allowances' }), { available: false, detail: 'Configure the image route.' });
  assert.deepEqual(imageToggle(undefined, undefined), { available: false, detail: 'Checking…' });
  for (const view of ['features/agent/conversation-view.tsx', 'features/agent/home-view.tsx']) {
    const source = read(view);
    assert.match(source, /const imageState = imageToggle\(imageCapability, usage\.data, usage\.isLoading\)/, view);
    assert.match(source, /if \(imageRequested && !imageState\.available\) setImageRequested\(false\)/, `${view} turns a now-unavailable image request off`);
    assert.doesNotMatch(source, /imageCapability\?\.detail/, `${view} no longer shows the catalog detail`);
  }
  assert.match(read('features/agent/composer.tsx'), /!imageGeneration\.available && <span className='sr-only'>/, 'the reason is read with the disabled toggle');
});

test('Radar: a credit plan’s daily watch says it does not run and is not offered', () => {
  const external = (spec) => !spec.startsWith('.') && !spec.startsWith('@/') || ['@/lib/workspace/provider', '@/lib/auth/access', '@/components/ui/button'].includes(spec) || spec.startsWith('./');
  const { monitorNotice } = load(join(SRC, 'features/growth/radar.tsx'), external);
  const catalog = (extra = {}) => ({ sources: [], consent: {}, monitor: { enabled: false }, monitoringAvailable: true, paidMonitoring: true, monitorMaximumUsdMicro: 1_000_000, ...extra });
  const blocked = monitorNotice(catalog({ monitoringBlocked: 'recurring_credit_authorization_unavailable' }));
  assert.equal(blocked.canEnable, false);
  assert.match(blocked.text, /credit/);
  assert.doesNotMatch(blocked.text, /paid plans/);
  const paused = monitorNotice(catalog({ monitoringBlocked: 'recurring_credit_authorization_unavailable', monitor: { enabled: true, query: 'piano', timezone: 'UTC' } }));
  assert.match(paused.text, /^Paused: .*nothing is charged/);
  const legacy = monitorNotice(catalog());
  assert.equal(legacy.canEnable, true);
  assert.match(legacy.text, /\$1/);
  assert.equal(monitorNotice(catalog({ paidMonitoring: false })).canEnable, false);
  assert.equal(monitorNotice(catalog({ monitoringAvailable: false })).text, 'Daily monitoring is not enabled yet.');
});
