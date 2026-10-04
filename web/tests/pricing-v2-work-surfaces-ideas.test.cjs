const { test } = require('node:test'); const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module'), ts = require('typescript');
const { execFileSync } = require('node:child_process');
function load(relative, mocks = {}) {
  const file = path.resolve(__dirname, '../src', relative), m = new Module(file); m.paths = module.paths;
  m.require = id => Object.hasOwn(mocks, id) ? mocks[id] : require(id);
  const source = global.__task9SourceMode === 'base' && relative === 'features/ideas/use-draft.ts'
    ? execFileSync('git', ['show', '0e8d05b7d7d5f8ecedc0d5b0784d8d737655e9f0:web/src/features/ideas/use-draft.ts'], { encoding: 'utf8', cwd: path.resolve(__dirname, '../..') })
    : fs.readFileSync(file, 'utf8');
  m._compile(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, file); return m.exports;
}
function fixture(mode = 'managed_credits', cost = 'paid', modelReady = true) {
  let cursor = 0; const slots = [], calls = [];
  const react = {
    useMemo: fn => fn(), useRef: value => { const i = cursor++; return slots[i] ??= { current: value }; },
    useState: value => { const i = cursor++; if (!(i in slots)) slots[i] = value; return [slots[i], next => { slots[i] = typeof next === 'function' ? next(slots[i]) : next; }]; }
  };
  const usage = { billingMode: mode, aiUsageExempt: false, entitlement: { writingBatchesRemaining: 0 }, credits: mode === 'managed_credits' ? { availableMilliCredits: 5000, spendAvailable: true } : null };
  const api = { snapshot: async () => ({ revision: 7 }), createConversation: async () => { calls.push(['conversation']); return { conversationId: 'c' }; }, creditQuote: async (_w, body) => { calls.push(['quote', body]); return { quoteId: 'q' }; }, quickStart: async (_w, _r, body) => { calls.push(['quick-start', body]); return { runId: 'r', conversationId: 'c' }; }, turn: async (_w, _c, body) => { calls.push(['turn', body]); return { runId: 'r', conversationId: 'c' }; } };
  const mocks = {
    react, 'next/navigation': { useRouter: () => ({ push: url => calls.push(['navigate', url]) }) },
    '@tanstack/react-query': { useQueryClient: () => ({ setQueryData: () => {}, invalidateQueries: async () => {} }) },
    '@/features/agent/composer': { DRAFT_PLATFORMS: ['LinkedIn'] },
    '@/features/agent/use-model': { useModelChoice: () => ({ option: { costClass: cost }, requestFields: { model: 'selected-writer' }, label: 'Selected writer', auto: false, model: 'selected-writer' }) },
    '@/lib/api/hooks': { keys: new Proxy({}, { get: () => () => [] }), useSnapshot: () => ({ data: { revision: 7, state: { phase2: { channels: [] } } } }), useModels: () => ({ isSuccess: modelReady }), useUsage: () => ({ data: usage }) },
    '@/lib/preferences': { useTimeZone: () => 'UTC' }, '@/lib/workspace/provider': { useWorkspaceApi: () => ({ api, workspaceId: 'w' }) },
    './use-sources': { detectLanguage: () => 'en-US', useActError: () => error => calls.push(['error', error.message]) },
    '@/features/agent/credit-turn': load('features/agent/credit-turn.ts'),
    '@/features/agent/use-credit-estimate': { useCreditEstimate: (enabled, body) => { if (enabled) calls.push(['estimate', body]); return { estimate: { ceilingMilliCredits: 1200, estimateMilliCredits: 100 }, error: null, loading: false }; } },
    '@/features/agent/credit-limit': load('features/agent/credit-limit.ts'), '@/features/agent/work-surface-policy': load('features/agent/work-surface-policy.ts')
  };
  const useDraft = load('features/ideas/use-draft.ts', mocks).useDraftHandoff;
  return { calls, render: () => { cursor = 0; return useDraft(); } };
}
test('Ideas capture on a zero-batch credit plan prepares an exact quote, then waits for approval', async () => {
  const f = fixture(); let draft = f.render();
  await draft.quickStart({ text: 'Keep my exact facts', ownContent: true });
  assert.equal(f.calls.filter(c => c[0] === 'quick-start').length, 0, 'no paid quick-start before review');
  draft = f.render(); assert.equal(draft.creditApproval.request.text, 'Keep my exact facts');
  draft.setMaximum('1.1'); draft = f.render(); assert.equal(draft.approvalInvalid, true); await draft.approve(); assert.equal(f.calls.some(c => c[0] === 'quote'), false);
  draft.setMaximum('1.2'); draft = f.render(); assert.equal(draft.approvalInvalid, false); await draft.approve();
  assert.deepEqual(f.calls.filter(c => ['quote', 'quick-start'].includes(c[0])).map(c => c[0]), ['quote', 'quick-start']);
  assert.equal(f.calls.find(c => c[0] === 'quote')[1].maxMilliCredits, 1200);
  assert.equal(f.calls.find(c => c[0] === 'quick-start')[1].creditQuoteId, 'q');
});
test('Ideas source handoff quotes the dedicated turn for the exact source and destination', async () => {
  const f = fixture(); let draft = f.render();
  await draft.fromSource({ id: 'source-1', title: 'My evidence', text: 'My exact facts', kind: 'text', origin: { executionPlan: { platform: 'LinkedIn', account: 'a', language: 'en-US' } } });
  assert.equal(f.calls.some(c => c[0] === 'turn'), false, 'creating a conversation cannot authorize a model');
  draft = f.render(); draft.setMaximum('1.2'); draft = f.render(); await draft.approve();
  const quote = f.calls.find(c => c[0] === 'quote')[1]; assert.equal(quote.operation, 'turn'); assert.equal(quote.conversationId, 'c');
  assert.deepEqual(quote.request.sourceIds, ['source-1']); assert.equal(quote.request.destinations[0].channelId, 'a');
  assert.equal(f.calls.find(c => c[0] === 'turn')[1].creditQuoteId, 'q');
});
test('Free managed Ideas cannot send quick-start or create a paid source handoff', async () => {
  const f = fixture('free_preview'); const draft = f.render();
  await draft.quickStart({ text: 'Keep this idea', ownContent: true }); await draft.fromSource({ id: 's', kind: 'idea', title: 'Idea', text: 'Idea' });
  assert.equal(f.calls.length, 0); assert.match(draft.blocked, /Free/);
});
test('Ideas cannot create a conversation or draft with an unresolved model catalog', async () => {
  const f = fixture('managed_credits', 'paid', false); const draft = f.render();
  await draft.quickStart({ text: 'Keep this idea', ownContent: true }); await draft.fromSource({ id: 's', kind: 'idea', title: 'Idea', text: 'Idea' });
  assert.equal(f.calls.length, 0); assert.match(draft.blocked, /availability|loading/);
});
test('legacy, CLI and BYOK Ideas keep their existing dedicated transport without a managed quote', async () => {
  for (const [mode, cost] of [['legacy_allowances', 'paid'], ['managed_credits', 'subscription'], ['managed_credits', 'byok']]) {
    const f = fixture(mode, cost); await f.render().quickStart({ text: 'My facts', ownContent: true });
    assert.equal(f.calls.some(c => c[0] === 'quote'), false); assert.equal(f.calls.filter(c => c[0] === 'quick-start').length, 1);
  }
});
test('Overview and Home retain actionable reminders while removing only the stale v2 batch warning', () => {
  const file = path.resolve(__dirname, '../src/features/overview/work-attention.ts'); const m = new Module(file);
  m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, file);
  const items = [{ id: 'writing-allowance' }, { id: 'approvals' }, { id: 'account-expired' }];
  assert.deepEqual(m.exports.workAttention(items, 'managed_credits'), items.slice(1));
  assert.deepEqual(m.exports.workAttention(items, 'free_preview'), items.slice(1));
  assert.equal(m.exports.workAttention(items, 'legacy_allowances'), items);
});
