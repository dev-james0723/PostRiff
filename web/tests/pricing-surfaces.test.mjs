/**
 * Public new-sale surfaces under both catalogs (Pricing v2 Task 7; spec §13.1–13.2; PRD R-COM-04, AC01/AC05).
 * Legacy stays exactly today's copy until NEXT_PUBLIC_PRICING_CATALOG=v2; v2 sells Free and Creator only, leads with
 * outcomes, explains credits once, never says "trial", "writing batches", US$19/39 or "Two plans", and never offers a
 * buy button that cannot work.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const WEB = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(WEB, 'src');

/** Load a TypeScript module the way the app sees it: `@/…` resolves to src, type-only imports vanish. */
function load(file, cache = new Map()) {
  if (cache.has(file)) return cache.get(file).exports;
  const out = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023, jsx: ts.JsxEmit.ReactJSX } });
  const mod = { exports: {} };
  cache.set(file, mod);
  const local = (spec) => {
    if (!spec.startsWith('@/') && !spec.startsWith('.')) return require(spec);
    const base = spec.startsWith('@/') ? join(SRC, spec.slice(2)) : join(dirname(file), spec);
    for (const candidate of [`${base}.ts`, `${base}.tsx`, join(base, 'index.ts')]) {
      try {
        if (statSync(candidate).isFile()) return load(candidate, cache);
      } catch {}
    }
    throw new Error(`Cannot resolve ${spec} from ${file}`);
  };
  new Function('require', 'module', 'exports', out.outputText)(local, mod, mod.exports);
  return mod.exports;
}

const read = (path) => readFileSync(join(SRC, path), 'utf8');
const { marketingCopy, v2CompareRows } = load(join(SRC, 'config/pricing-copy.ts'));
const legacy = marketingCopy('legacy');
const v2 = marketingCopy('v2');

const STALE_V2 = [/writing batch/i, /\$19\b/, /\$39\b/, /US\$19/, /US\$39/, /\btrial\b/i, /Studio Assist/i, /\bStudio\b/, /\bStarter\b/, /media credit/i, /two plans/i, /after trial/i, /introductory pricing/i, /\bproven\b/i, /optimi[sz]ed price/i, /top[- ]?up/i];

test('legacy copy is exactly today’s, so nothing changes before activation', () => {
  assert.equal(legacy.catalog, 'legacy');
  assert.equal(legacy.pricingMeta.description, 'Simple monthly plans. 14-day trial, no card. Allowances stop at the limit — never a surprise charge.');
  assert.deepEqual(legacy.pricingHero, { eyebrow: 'Pricing', title: 'Simple pricing.', accent: 'No surprises.', description: 'Start with a 14-day trial — 2 connected accounts, 10 writing batches, no card. Pick a plan when you are ready.' });
  assert.equal(legacy.pricingFootnote, 'Prices are shown in USD. Introductory pricing applies to early customers; see the FAQ below.');
  assert.equal(legacy.pricingFaq.length, 5);
  assert.equal(legacy.pricingFaq[2].q, 'What does “introductory pricing” mean?');
  assert.deepEqual(legacy.landingPricing, { title: 'Two plans.', accent: 'No surprises.', description: '14-day trial with 2 connected accounts and 10 writing batches. No card, no automatic conversion.', compareLink: 'Compare plans in detail' });
  assert.deepEqual(legacy.landingFaqItem, { q: 'How does the trial work?', a: '14 days, 2 connected accounts, 10 writing batches, no card. It never converts into a paid plan by itself.' });
  assert.deepEqual(legacy.ctaBand, { description: 'Start a 14-day trial with two connected accounts and ten writing batches. Export everything, any time.', primaryLabel: 'Start free trial', note: 'No credit card required during the trial.' });
  assert.deepEqual(legacy.hero, { primaryLabel: 'Start free trial', note: 'No credit card · 14-day trial · Export everything, any time' });
  assert.equal(legacy.headerCta, 'Start free trial');
  assert.deepEqual(legacy.previewStat, ['Writing batches', '61']);
  assert.equal(legacy.terms.title, 'Trial, subscriptions and billing');
  assert.match(legacy.terms.paragraph, /^New workspaces get a 14-day trial with 2 connected accounts and 10 writing batches\. No payment method is required/);
  assert.deepEqual([legacy.signUp.metaTitle, legacy.signUp.metaDescription, legacy.signUp.subtitle, legacy.signUp.showPlanChooser], ['Start your free trial', 'Create a Rafii workspace. 14-day trial, no card required.', '14-day free trial. No card needed.', true]);
  assert.equal(legacy.docs.gettingStartedCreate, 'Sign up with Google or an email code and choose a trial plan. A workspace is created for you; you are its owner.');
  assert.deepEqual(legacy.docs.usageSections.map((s) => s.heading), ['Allowances', 'Trial', 'Subscriptions']);
});

test('v2 copy never uses legacy sales language anywhere a prospect can read it', () => {
  // Terms and help may truthfully say that a trial already running continues; new-sale copy never mentions one.
  const { terms, docs, ...sales } = v2;
  const text = JSON.stringify({ ...sales, compare: v2CompareRows() });
  for (const re of STALE_V2) assert.doesNotMatch(text, re, `v2 sales copy matches ${re}`);
  const reference = JSON.stringify({ terms, docs });
  for (const re of STALE_V2.filter((re) => re.source !== '\\btrial\\b')) assert.doesNotMatch(reference, re, `v2 terms/help match ${re}`);
  assert.doesNotMatch(reference, /free trial|start (?:a|your) trial|after trial/i);
});

test('v2 leads with outcomes and the two plans, with numbers from the catalog', () => {
  assert.equal(v2.catalog, 'v2');
  assert.match(v2.pricingMeta.description, /US\$59/);
  assert.match(v2.pricingMeta.description, /3,500 managed credits/);
  assert.match(v2.pricingHero.description, /one Post Doctor check/i);
  assert.match(v2.pricingHero.description, /up to 20 recent posts/);
  assert.match(v2.landingPricing.description, /Free/);
  assert.match(v2.landingPricing.description, /Creator is US\$59 a month with 3,500 managed credits/);
  assert.match(v2.pricingFootnote, /USD/);
  assert.match(v2.pricingFootnote, /beta/i, 'Creator pricing is still being validated, not proven');
});

test('v2 explains managed credits in one compact answer, after the outcome questions', () => {
  const credits = v2.pricingFaq.filter((item) => /credit/i.test(item.q));
  assert.equal(credits.length, 1, 'one compact credits answer');
  const first = v2.pricingFaq.findIndex((item) => /credit/i.test(item.q));
  assert.ok(first >= 1, 'an outcome question comes first');
  const [answer] = credits.map((item) => item.a);
  assert.match(answer, /300 credits/);
  assert.match(answer, /US\$1/);
  assert.match(answer, /failed task uses no credits/i);
  assert.match(answer, /nothing is charged silently/i);
  assert.match(answer, /don’t roll over/);
  assert.ok(v2.pricingFaq.some((item) => /subscribed before/i.test(item.q) && /keep their price/i.test(item.a)), 'earlier subscribers are reassured without naming legacy prices');
});

test('v2 sign-up starts free with no card and no "after trial" price', () => {
  assert.equal(v2.signUp.showPlanChooser, false);
  assert.match(v2.signUp.subtitle, /Start free/);
  assert.match(v2.signUp.subtitle, /No card/i);
  assert.ok(v2.signUp.promise.length >= 3);
  assert.ok(v2.signUp.promise.some((line) => /Creator/.test(line)));
  assert.doesNotMatch(JSON.stringify(v2.signUp), /trial|\/mo/i);
  assert.equal(v2.hero.primaryLabel, 'Start free');
  assert.equal(v2.headerCta, 'Start free');
  assert.equal(v2.ctaBand.primaryLabel, 'Start free');
});

test('v2 terms keep the legal guarantees and state the credit rules', () => {
  const { title, paragraph } = v2.terms;
  assert.match(title, /Free/);
  assert.match(paragraph, /3,500 managed credits/);
  assert.match(paragraph, /300 credits/);
  assert.match(paragraph, /do not roll over/);
  assert.match(paragraph, /no automatic overage charge/);
  assert.match(paragraph, /at least 30 days’ notice/);
  assert.match(paragraph, /\[Refund policy — to be confirmed by counsel\.\]/);
  assert.match(paragraph, /Taxes are shown at checkout/);
  assert.match(paragraph, /earlier plan keep/);
});

test('v2 help explains Free, credits and earlier plans without batch language', () => {
  assert.doesNotMatch(v2.docs.gettingStartedCreate, /trial/i);
  const headings = v2.docs.usageSections.map((s) => s.heading);
  assert.deepEqual(headings, ['Free', 'Managed credits', 'Limits', 'Earlier plans', 'Subscriptions']);
  assert.match(JSON.stringify(v2.docs.usageSections), /unknown cost stays held/i);
});

test('v2 comparison has one column per plan for sale and no storage headline', () => {
  const rows = v2CompareRows();
  assert.ok(rows.every((row) => row.values.length === 2));
  const byLabel = Object.fromEntries(rows.map((row) => [row.label, row.values]));
  assert.deepEqual(byLabel['Managed AI credits'], ['None', '3,500 / month']);
  assert.deepEqual(byLabel['Connected accounts'], ['1', 'Up to 6']);
  assert.deepEqual(byLabel.Brands, ['1', 'Up to 2']);
  assert.deepEqual(byLabel.Seats, ['1', '1']);
  assert.ok(!rows.some((row) => /storage/i.test(row.label)));
});

test('public surfaces read pricing words from the catalog modules, not hard-coded legacy copy', () => {
  const surfaces = {
    'app/(marketing)/pricing/page.tsx': [/14-day/, /writing batches/i, /Introductory pricing/],
    'components/marketing/landing/sections.tsx': [/Two plans/, /How does the trial work/],
    'components/marketing/cta-band.tsx': [/14-day trial/, /Start free trial/, /during the trial/],
    'components/marketing/landing/hero.tsx': [/14-day trial/, /Start free trial/],
    'components/marketing/landing/product-preview.tsx': [/'Writing batches'/],
    'components/marketing/site-header.tsx': [/>\s*Start free trial\s*</],
    'components/marketing/mobile-nav.tsx': [/>\s*Start free trial\s*</],
    'app/(marketing)/channels/[slug]/page.tsx': [/>\s*Start free trial\s*</],
    'components/auth/auth-form.tsx': [/after trial/, /14-day free trial/],
    'app/auth/sign-up/page.tsx': [/14-day trial/],
    'app/(marketing)/terms/page.tsx': [/writing batches/],
    'content/docs.ts': [/choose a trial plan/, /Writing batches, media credits/]
  };
  for (const [path, patterns] of Object.entries(surfaces)) {
    const source = read(path);
    for (const re of patterns) assert.doesNotMatch(source, re, `${path} still hard-codes ${re}`);
  }
  assert.match(read('components/marketing/json-ld.tsx'), /jsonLdOffers\(/);
  assert.match(read('app/(marketing)/pricing/page.tsx'), /PRICING_CATALOG/);
});
