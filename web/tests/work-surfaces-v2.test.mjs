/**
 * Work surfaces without writing-batch assumptions under Pricing v2 (Task 9; spec §13.4; PRD R-COM-04, AC05).
 * A Creator workspace has writingBatchesRemaining = 0 by design: nothing may read that as "used up". v2 surfaces speak
 * credits (Creator) or say managed writing isn't on Free; legacy workspaces keep their batch language unchanged.
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
const NOW = 1_800_000_000;
const DAY = 86400;

const wallet = (extra = {}) => ({
  mode: 'credits',
  availableMilliCredits: 2_140_000,
  heldMilliCredits: 0,
  usedMilliCredits: 0,
  debtMilliCredits: 0,
  currentPeriodGrantMilliCredits: 3_500_000,
  currentPeriodExpiresAt: NOW + 5 * DAY,
  quoteType: 'spending_limit',
  textOnly: true,
  ...extra
});
const entitlement = (left, source = 'subscription') => ({ writingBatchesRemaining: left, mediaCreditsRemaining: 0, resetsAt: NOW + 5 * DAY, source, planTermsId: 'creator-v1' });

test('attention: a Creator with 0 batches and credits left is not "used up"; credits speak credits', () => {
  const { deriveAttention } = load(join(SRC, 'lib/attention.ts'));
  const run = (data) => deriveAttention({ snapshot: { isError: false, data: undefined }, channels: { isError: false, data: undefined }, usage: { isError: false, data }, now: NOW });
  const item = (data) => run(data).items.find((i) => i.id === 'writing-allowance');
  const creator = (credits) => ({ billingMode: 'managed_credits', credits, entitlement: entitlement(0), lifecycle: { status: 'active' } });

  assert.equal(item(creator(wallet())), undefined);
  const out = item(creator(wallet({ availableMilliCredits: 0 })));
  assert.equal(out.title, 'Managed credits used up');
  assert.equal(out.tone, 'warning');
  assert.equal(out.href, '/app/account/billing');
  assert.match(out.description, /nothing extra is charged/);
  assert.match(out.description, /in 5 days/);
  const low = item(creator(wallet({ availableMilliCredits: 300_000 })));
  assert.equal(low.title, '300 managed credits left');
  assert.equal(low.tone, 'info');
  assert.equal(item(creator(wallet({ debtMilliCredits: 4_000 }))).title, 'Billing adjustment pending');
  for (const found of [out, low]) assert.doesNotMatch(`${found.title} ${found.description}`, /batch/i);

  const free = { billingMode: 'free_preview', credits: null, entitlement: entitlement(0, 'free'), lifecycle: { status: 'free' } };
  assert.equal(item(free), undefined, 'Free has no recurring allowance to run out of');
  assert.equal(run(free).items.find((i) => i.id === 'trial'), undefined);
  const legacy = { billingMode: 'legacy_allowances', credits: null, entitlement: entitlement(0), lifecycle: { status: 'active' } };
  assert.equal(item(legacy).title, 'Writing allowance used up', 'legacy keeps its own words');
});

test('model costs: managed credits for Creator, the Creator plan for Free, batches only for legacy', () => {
  const { costCopy } = load(join(SRC, 'features/account/models/catalog.ts'));
  assert.deepEqual(costCopy('paid', { kind: 'batches', remaining: 3, resetsAt: null }), { badge: 'Writing batches', line: 'Uses one writing batch from your plan per finished run. Failed runs don’t count.' });
  const credits = costCopy('paid', { kind: 'credits', available: 10, resetsAt: null, debt: 0 });
  assert.equal(credits.badge, 'Managed credits');
  assert.doesNotMatch(credits.line, /batch/i);
  assert.equal(costCopy('paid', { kind: 'free' }).badge, 'Creator plan');
  assert.doesNotMatch(JSON.stringify(costCopy('paid')), /batch/i, 'before usage loads, no batch claim');
  assert.equal(costCopy('none').badge, 'Free');
  assert.equal(costCopy('subscription').badge, 'Your CLI subscription');
});

test('writing surfaces read the billing mode, not writingBatchesRemaining', () => {
  for (const path of ['features/account/models/writing-now.tsx', 'features/ideas/capture-card.tsx', 'features/ideas/ideas-view.tsx']) {
    const source = read(path);
    assert.doesNotMatch(source, /writingBatchesRemaining/, `${path} reads batches directly`);
    assert.match(source, /writingAllowance\(/, `${path} uses the mode-aware allowance`);
  }
  const models = read('features/account/models-view.tsx');
  assert.match(models, /infoContent=\{infoContentFor\(allowance\)\}/, 'the models page info follows the mode');
  assert.match(models, /credits: 'The managed model, which uses managed credits from your plan\.'/);
  assert.match(models, /free: 'The managed model, which needs the Creator plan\.'/);
});

test('tours, help suggestions and labels say nothing a v2 workspace cannot do', () => {
  const guides = read('features/rafii-guide/guides.ts');
  const plan = guides.slice(guides.indexOf("id: 'check_plan'"), guides.indexOf("id: 'check_plan'") + 900);
  assert.doesNotMatch(plan, /media credits|top up/i, 'the plan tour is mode-neutral and promises no top-up');
  const panel = read('lib/site-agent/panel-logic.ts');
  assert.doesNotMatch(panel, /writing batches/i);

  const { planLabel } = load(join(SRC, 'features/account/profile-model.ts'));
  assert.equal(planLabel({ plan: 'free', trialPlan: null }), 'Free');
  assert.equal(planLabel({ plan: 'creator', trialPlan: null }), 'Creator');
  assert.equal(planLabel({ plan: 'starter', trialPlan: null }), 'Starter');
  assert.equal(planLabel({ plan: 'assist', trialPlan: null }), 'Studio Assist');
  assert.equal(planLabel({ plan: 'trial', trialPlan: 'studio' }), 'Trial · Studio');

  const { describeAuditEvent } = load(join(SRC, 'features/workspace/audit/audit-model.ts'));
  const lookup = { channels: new Map(), providers: [], providerBySubject: new Map(), invitations: new Map(), members: new Map() };
  const created = (plan) => describeAuditEvent({ kind: 'workspace.created', subject: '', meta: { plan }, at: NOW }, lookup).detail;
  assert.equal(created('free'), 'Started on Free.');
  assert.equal(created('studio'), 'Started on a trial of Studio.');

  const { CATEGORY_LABELS } = load(join(SRC, 'features/coworker/notifications/labels.ts'));
  assert.doesNotMatch(CATEGORY_LABELS.billing.hint, /trial/i);
  const emails = read('features/account/notifications-view.tsx');
  assert.match(emails, /mode === 'free_preview' \|\| mode === 'managed_credits' \? EMAILS\.filter\(\(item\) => !item\.trial\)/, 'trial emails are listed only where trials exist');
});
