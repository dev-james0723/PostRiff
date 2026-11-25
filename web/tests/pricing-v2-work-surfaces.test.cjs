const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
function load(relative) {
  const file = path.resolve(__dirname, '../src', relative);
  assert.ok(fs.existsSync(file), `${relative} must implement the actual work-surface boundary`);
  const m = new Module(file); m.paths = module.paths;
  m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, file);
  return m.exports;
}
const usage = (billingMode, extra = {}) => ({ billingMode, entitlement: { writingBatchesRemaining: 0, mediaCreditsRemaining: 0 }, credits: billingMode === 'managed_credits' ? { availableMilliCredits: 10000, spendAvailable: true } : null, freePreview: null, aiUsageExempt: false, ...extra });
test('credit estimates preserve unsupported research intent for an honest server refusal', () => {
  const input = { text: 'Look this up', research: true, imageGeneration: { enabled: true, count: 1 }, idempotencyKey: 'k', creditQuoteId: 'old' };
  const result = load('features/agent/credit-turn.ts').creditRequestFor(input);
  assert.equal(result.research, true); assert.deepEqual(result.imageGeneration, input.imageGeneration);
  assert.equal(result.idempotencyKey, undefined); assert.equal(result.creditQuoteId, undefined); assert.equal(input.creditQuoteId, 'old');
});
for (const model of ['cli/writer', 'byok/writer', 'cloud/writer']) for (const operation of ['quick-start', 'turn']) {
  test(`${operation} binds the same image payload and explicitly approved maximum with ${model}`, async () => {
    const c = load('features/agent/credit-turn.ts'), calls = [];
    const request = { text: 'A piano', model, imageGeneration: { enabled: true, count: 1 }, idempotencyKey: 'same-key' };
    const api = { snapshot: async () => ({ revision: 7 }), creditQuote: async (_w, body) => { calls.push(['quote', structuredClone(body)]); return { quoteId: 'q' }; }, quickStart: async (_w, _r, body) => { calls.push(['submit', body]); return { runId: 'r' }; }, turn: async (_w, _c, body) => { calls.push(['submit', body]); return { runId: 'r' }; } };
    const props = { api, workspaceId: 'w', conversationId: 'c', expectedRevision: 7, request, maxMilliCredits: 3100 };
    await (operation === 'turn' ? c.submitConversationTurn : c.submitQuickStart)(props);
    assert.equal(calls[0][1].maxMilliCredits, 3100);
    const submitted = structuredClone(calls[1][1]); delete submitted.creditQuoteId; delete submitted.expectedRevision;
    assert.deepEqual(submitted, calls[0][1].request); assert.deepEqual(c.creditRequestFor(submitted), c.creditRequestFor(request));
    assert.equal(request.creditQuoteId, undefined);
  });
}
test('research is refused before any approval or dispatch, without mutating input', async () => {
  const c = load('features/agent/credit-turn.ts'); let io = 0;
  const request = { text: 'Research', research: true, idempotencyKey: 'k' };
  await assert.rejects(c.submitQuickStart({ api: { creditQuote: async () => { io++; }, quickStart: async () => { io++; } }, workspaceId: 'w', expectedRevision: 1, request, maxMilliCredits: 1000 }), /research/i);
  assert.equal(io, 0); assert.equal(request.research, true);
});
test('billing mode and independent image qualification control execution, never batch counts', () => {
  const { workSurfacePolicy } = load('features/agent/work-surface-policy.ts');
  assert.equal(workSurfacePolicy(usage('managed_credits'), 'paid', false).creditMode, true);
  assert.equal(workSurfacePolicy(usage('managed_credits'), 'paid', false).blocked, null);
  for (const cost of ['none', 'own', 'subscription']) {
    assert.equal(workSurfacePolicy(usage('managed_credits'), cost, false).creditMode, false);
    assert.equal(workSurfacePolicy(usage('managed_credits'), cost, true, { available: true, creditEstimateAvailable: true }).creditMode, true);
    assert.match(workSurfacePolicy(usage('managed_credits'), cost, true, { available: true, creditEstimateAvailable: false }).blocked, /estimate/i);
  }
  assert.match(workSurfacePolicy(usage('free_preview'), 'paid', false).blocked, /Free/);
  assert.equal(workSurfacePolicy(usage('free_preview'), 'subscription', false).blocked, null);
  assert.equal(workSurfacePolicy(usage('legacy_allowances'), 'paid', false).blocked, null);
  assert.equal(workSurfacePolicy(usage('legacy_allowances'), 'paid', true, { available: true, creditEstimateAvailable: false }).blocked, null);
  assert.match(workSurfacePolicy(usage('managed_credits', { credits: null }), 'paid', false).blocked, /available/i);
  assert.equal(workSurfacePolicy(usage('managed_credits', { credits: null, aiUsageExempt: true }), 'paid', false).blocked, null);
  assert.ok(workSurfacePolicy(usage('managed_credits', { credits: null, aiUsageExempt: true }), 'own', true, { available: true, creditEstimateAvailable: true }).blocked);
});
test('media approval refuses a fresh ceiling above the displayed cap before quote/read', async () => {
  const { readWithCredit } = load('features/agent/attachments/read-with-credit.ts'); const calls = [];
  const api = { creditEstimate: async () => ({ cached: false, ceilingMilliCredits: 200, stateRevision: 2 }), creditQuote: async () => { calls.push('quote'); return { quoteId: 'q' }; }, mediaNotes: async () => { calls.push('read'); return { status: 'ready' }; } };
  await assert.rejects(readWithCredit({ api, workspaceId: 'w', assetId: 'a', idempotencyKey: 'k', approvalRequired: true, approvedMaxMilliCredits: 100 }), /maximum|limit/i);
  assert.deepEqual(calls, []);
});
test('media quote uses approved MAX, cache remains free, Free cannot approve paid notes', async () => {
  const { readWithCredit, formatMediaCredits } = load('features/agent/attachments/read-with-credit.ts'); const calls = [];
  let cached = false;
  const api = { creditEstimate: async () => ({ cached, ceilingMilliCredits: 100, stateRevision: 2 }), creditQuote: async (_w, body) => { calls.push(body); return { quoteId: 'q' }; }, mediaNotes: async (_w, body) => { calls.push(body); return { status: 'ready' }; } };
  await readWithCredit({ api, workspaceId: 'w', assetId: 'a', idempotencyKey: 'k', approvalRequired: true, approvedMaxMilliCredits: 300 });
  assert.equal(calls[0].maxMilliCredits, 300); assert.equal(calls[1].creditQuoteId, 'q');
  calls.length = 0; cached = true;
  await readWithCredit({ api, workspaceId: 'w', assetId: 'a', idempotencyKey: 'k', approvalRequired: true, approvedMaxMilliCredits: null }); assert.equal(calls.length, 1); assert.equal(calls[0].creditQuoteId, undefined);
  calls.length = 0; cached = false;
  await assert.rejects(readWithCredit({ api, workspaceId: 'w', assetId: 'a', idempotencyKey: 'k', approvalRequired: true, paidUnavailable: true, approvedMaxMilliCredits: 300 })); assert.equal(calls.length, 0);
  assert.equal(formatMediaCredits(100), '0.1'); assert.equal(formatMediaCredits(1200), '1.2');
});
test('Free Growth uses real lifetime eligibility; unqualified managed routes cannot execute', () => {
  const { growthAvailability } = load('features/growth/availability.ts');
  const free = usage('free_preview', { freePreview: { postDoctor: { remaining: 1, eligible: false, reason: 'funding_unavailable' }, genome: { remaining: 1, eligible: true, reason: null, maxPosts: 20 } } });
  assert.equal(growthAvailability(free, 'check').available, false); assert.match(growthAvailability(free, 'check').detail, /funding/i);
  assert.equal(growthAvailability(free, 'genome').available, true); assert.match(growthAvailability(free, 'genome').detail, /20/);
  for (const mode of ['free_preview', 'managed_credits']) for (const kind of ['rewrite', 'audience', 'postmortem', 'radar', 'calibration']) assert.equal(growthAvailability(usage(mode), kind).available, false);
  assert.equal(growthAvailability(usage('legacy_allowances'), 'rewrite').available, true);
});
