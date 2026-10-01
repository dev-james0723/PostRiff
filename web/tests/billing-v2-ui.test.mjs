/**
 * Usage & plan wiring under Pricing v2 (Task 8; spec §13.3). The pure rules live in lib/billing/mode.ts (billing-mode.test.mjs);
 * these checks pin how the page uses them: one branch per billing mode, the credit meter and Free preview in place of
 * legacy meters, Free + Creator plan cards at the workspace's own price, and info copy that matches the mode.
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
const { infoContent, infoContentFor } = load(join(SRC, 'features/billing/billing-copy.ts'));

test('the info panel follows the billing mode: legacy keeps batches, v2 explains credits or the Free preview', () => {
  assert.equal(infoContentFor('legacy_allowances'), infoContent);
  const managed = JSON.stringify(infoContentFor('managed_credits'));
  assert.match(managed, /300 credits equal US\$1/);
  assert.match(managed, /No silent overage/);
  assert.doesNotMatch(managed, /writing batch|trial/i);
  const free = JSON.stringify(infoContentFor('free_preview'));
  assert.match(free, /Post Doctor/);
  assert.doesNotMatch(free, /writing batch|trial/i);
  const unknown = JSON.stringify(infoContentFor(null));
  assert.doesNotMatch(unknown, /writing batch|trial/i, 'before the mode is known, only what holds for every plan');
  assert.match(JSON.stringify(infoContentFor('managed_credits', 'zh-Hant')), /代管點數/);
});

test('the page has one branch per billing mode, never a branch on a price, batches or a wallet alone', () => {
  const view = read('features/billing/billing-view.tsx');
  assert.match(view, /const mode = billingModeOf\(data\)/);
  assert.match(view, /mode === 'managed_credits' \?[\s\S]*<CreditMeterCard/);
  assert.match(view, /mode === 'free_preview' \?[\s\S]*<FreePreviewCard/);
  assert.match(view, /mode === 'legacy_allowances' \?[\s\S]*data\.credits \? <CreditBalance[\s\S]*<Allowances usage=\{data\}/);
  assert.match(view, /only='capacity'/, 'v2 keeps account and seat limits without batch or media meters');
  assert.match(view, /isOwner && data\.budget && <CostGuardSection/, 'provider cost stays owner-only and apart from credits');
  assert.ok(view.includes('data.credits && isOwner && <CreditPacks'), 'packs stay owner-only and server-gated');
  const packs = read('features/billing/credit-packs.tsx');
  assert.match(packs, /if \(!query\.data\?\.available && !query\.isError && !returned\) return null;/, 'inactive or unavailable packs never render');
});

test('the capacity-only view drops writing-batch and media-credit meters', () => {
  const allowances = read('features/billing/allowances.tsx');
  assert.match(allowances, /\.\.\.\(capacityOnly\s*\?\s*\[\]/);
  assert.match(allowances, /!capacityOnly && isOwner && usage\.budget && <CostGuard/);
});

test('the plan summary reads Free as Free, a subscriber’s own variant price, and labels kept legacy packages', () => {
  const card = read('features/billing/plan-card.tsx');
  assert.match(card, /mode === 'free_preview'/);
  assert.match(card, /title: v2Copy\.freeTitle/);
  assert.match(card, /isLegacyPlanUnderV2\(usage\)/);
  assert.match(card, /cents\(sub\.priceCents, sub\.currency\)/, 'subscription priceCents is the variant amount from the API');
  assert.match(card, /v2PlanCardModels\(usage, isOwner\)\.some\(\(card\) => card\.offer === 'checkout'\)/, '"See Creator" / "Choose a plan" only when the list offers a checkout');
});

test('the v2 plan list uses the v2 models and only shows Choose when checkout can work', () => {
  const plans = read('features/billing/plans.tsx');
  assert.match(plans, /if \(planListKind\(usage\) === 'v2'\) return <V2Plans/);
  assert.match(plans, /v2PlanCardModels\(usage, isOwner\)/);
  assert.match(plans, /offer === 'checkout' \?/);
  assert.match(plans, /copy\.notOpen/);
});
