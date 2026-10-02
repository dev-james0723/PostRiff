/* eslint-disable no-underscore-dangle -- Node Module's compilation API is required for source-bound tests. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module'), ts = require('typescript');
function load(file) {
  const absolute = path.resolve(__dirname, '../src/features/growth', file), m = new Module(absolute); m.paths = module.paths;
  assert.ok(fs.existsSync(absolute), `Implemented Growth boundary ${file} exists`);
  m._compile(ts.transpileModule(fs.readFileSync(absolute, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, absolute);
  return m.exports;
}
function find(node,predicate){ if (!node||typeof node!=='object') return null; if(predicate(node))return node; for(const child of [node.props?.children].flat(Infinity)){const found=find(child,predicate);if(found)return found;} return null; }
const request = () => ({ checkId: 'saved-check', model: 'selected-writer', facts: { fact1: 'My exact evidence' }, confirmed: true, requestKey: 'exact-rewrite-request-key' });
test('managed base checks use the exact server projection independently of rewrite and Free counters', () => {
  const { baseCheckAvailability } = load('availability.ts');
  const usage = { billingMode: 'managed_credits', freePreview: null };
  const catalog = { consented: true, postDoctor: true, rewriteCredits: { available: true, estimateAvailable: true }, baseChecks: { billingMode: 'managed_credits', available: true, reason: null } };
  assert.equal(baseCheckAvailability(usage, catalog, true).available, true);
  for (const baseChecks of [undefined, { billingMode: 'free', available: true }, { billingMode: 'managed_credits', available: false, reason: 'funding_unavailable' }, { billingMode: 'managed_credits', available: 'true' }]) assert.equal(baseCheckAvailability(usage, { ...catalog, baseChecks }, true).available, false);
  assert.equal(baseCheckAvailability(usage, catalog, false).available, false, 'failed cached catalog cannot authorize');
  assert.equal(baseCheckAvailability({ billingMode: 'free_preview', freePreview: { postDoctor: { eligible: true, remaining: 1 } } }, catalog, true).available, true);
  assert.equal(baseCheckAvailability({ billingMode: 'free_preview', freePreview: { postDoctor: { eligible: false, remaining: 0, reason: 'used' } } }, catalog, true).available, false);
  assert.equal(baseCheckAvailability({ billingMode: 'legacy_allowances' }, catalog, true).available, true);
});
test('actual managed check caller revalidates baseChecks before POST without any customer credit quote', async () => {
  const React = require('react'); let cursor = 0, freshAvailable = false, catalogReady = true; const slots = [], calls = [];
  const hooks = { ...React, useId: () => 'facts', useEffect: () => {}, useRef: value => { const i=cursor++; return slots[i] ??= {current:value}; }, useState: value => { const i=cursor++; if (!(i in slots)) slots[i]=value; return [slots[i],next=>slots[i]=typeof next==='function'?next(slots[i]):next]; } };
  const catalog = { postDoctor: true, postDoctorV2: true, consented: true, baseChecks: { billingMode: 'managed_credits', available: true, reason: null } };
  const api = { growthCatalog: async () => { calls.push(['catalog']); return { ...catalog, baseChecks: { ...catalog.baseChecks, available: freshAvailable, reason: freshAvailable ? null : 'funding_unavailable' } }; }, postDoctor: async (_w,body) => { calls.push(['check',body]); return { runId: 'saved-check' }; } };
  const source=path.resolve(__dirname,'../src/features/growth/post-doctor-panel.tsx'),m=new Module(source);m.paths=module.paths;
  const mocks={react:hooks,'@tanstack/react-query':{useQueryClient:()=>({})},'@/components/ui/button':{Button:()=>null},'@/components/ui/textarea':{Textarea:()=>null},'@/components/rafii':{Surface:()=>null},'@/lib/auth/access':{checkAccess:()=>true,useWorkspaceAccess:()=>({role:'owner'})},'@/lib/api/hooks':{useAct:()=>({}),useSnapshot:()=>({refetch:async()=>{}}),useUsage:()=>({data:{billingMode:'managed_credits'},refetch:async()=>{}})},'@/lib/workspace/provider':{useWorkspaceApi:()=>({api,workspaceId:'w'})},'./shared':{useGrowthCatalog:()=>({data:catalog,isSuccess:catalogReady,isError:!catalogReady,refetch:async()=>{}}),CheckResult:()=>null,GrowthConsent:()=>null},'./availability':load('availability.ts'),'./rewrite-with-credit':load('rewrite-with-credit.ts'),'@/features/agent/credit-limit':{parseCreditLimit:value=>Number(value)*1000},'./rewrite-credit-review':{RewriteCreditReview:()=>null}};
  m.require=id=>Object.hasOwn(mocks,id)?mocks[id]:require(id);m._compile(ts.transpileModule(fs.readFileSync(source,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,source);
  const render=()=>{cursor=0;return m.exports.PostDoctorPanel({variant:{id:'v',revision:1}});};
  let tree=render();find(tree,n=>n.props?.['aria-label']==='Allow AI analysis of this draft').props.onChange({target:{checked:true}});
  tree=render();let button=find(tree,n=>n.props?.children==='Check draft');assert.equal(button.props.disabled,false,'explicit qualified managed check is actionable');
  await button.props.onClick();await new Promise(r=>setImmediate(r));assert.deepEqual(calls.map(c=>c[0]),['catalog'],'fresh unavailable projection refuses before POST');
  freshAvailable=true;tree=render();await find(tree,n=>n.props?.children==='Check draft').props.onClick();await new Promise(r=>setImmediate(r));
  assert.deepEqual(calls.map(c=>c[0]),['catalog','catalog','check']);
  assert.deepEqual(calls[2][1],{goal:'general',variantId:'v',variantRevision:1,requestKey:calls[2][1].requestKey,confirmed:true});assert.match(calls[2][1].requestKey,/^[\da-f-]{36}$/);
  catalogReady=false;tree=render();assert.equal(find(tree,n=>n.props?.children==='Check this draft again').props.disabled,true);
});
const estimate = () => ({ operation: 'post-doctor-rewrite', estimateKind: 'maximum', estimateMilliCredits: 1200, ceilingMilliCredits: 1200, availableMilliCredits: 5000, basis: 'approved_growth_rewrite_ceiling', model: 'selected-writer', provider: 'vercel-ai-gateway', policy: 'qualified-policy', stateRevision: 7, cached: false });
function fixture() {
  const calls = []; let current = estimate();
  const api = {
    creditEstimate: async (_w, body) => { calls.push(['estimate', body]); return structuredClone(current); },
    creditQuote: async (_w, body) => { calls.push(['quote', body]); return { quoteId: 'exact-quote', maxMilliCredits: body.maxMilliCredits }; },
    postDoctorRewrite: async (_w, body) => { calls.push(['rewrite', body]); return { runId: 'saved-result', userMilliCreditsCharged: 300, userCreditsCharged: 0.3 }; }
  };
  return { api, calls, change: fields => { current = { ...current, ...fields }; } };
}
test('managed rewrite needs the actual qualified catalog, not consent or a cached failed query', () => {
  const { rewriteAvailability } = load('availability.ts');
  const usage = { billingMode: 'managed_credits' }, catalog = { consented: true, rewriteCredits: { billingMode: 'managed_credits', available: true, estimateAvailable: true, reason: null } };
  assert.equal(rewriteAvailability(usage, catalog, true).available, true);
  assert.equal(rewriteAvailability(usage, catalog, false).available, false);
  for (const projection of [undefined, { billingMode: 'managed_credits', available: false, estimateAvailable: false, reason: 'funding_unavailable' }, { billingMode: 'free', available: true, estimateAvailable: true }]) assert.equal(rewriteAvailability(usage, { ...catalog, rewriteCredits: projection }, true).available, false);
  assert.equal(rewriteAvailability({ billingMode: 'free_preview' }, catalog, true).available, false);
  assert.equal(rewriteAvailability({ billingMode: 'legacy_allowances' }, catalog, true).available, true);
});
test('rewrite freezes exact input, estimates a maximum, and quotes only after explicit approval', async () => {
  const { prepareRewrite, submitApprovedRewrite } = load('rewrite-with-credit.ts'); const f = fixture(), body = request();
  const approval = await prepareRewrite(f.api, 'w', body); body.facts.fact1 = 'Later edit';
  assert.deepEqual(f.calls.map(c => c[0]), ['estimate']);
  const quoted = []; const result = await submitApprovedRewrite(f.api, 'w', approval, 1200, body => quoted.push(body));
  assert.deepEqual(f.calls.map(c => c[0]), ['estimate', 'estimate', 'quote', 'rewrite']);
  assert.deepEqual(f.calls[2][1], { operation: 'post-doctor-rewrite', request: request(), expectedRevision: 7, maxMilliCredits: 1200 });
  assert.deepEqual(f.calls[3][1], { ...request(), expectedRevision: 7, creditQuoteId: 'exact-quote' });
  assert.deepEqual(quoted, [f.calls[3][1]]); assert.equal(result.userMilliCreditsCharged, 300);
});
test('rewrite below MAX refuses before quote or model submission', async () => {
  const { prepareRewrite, submitApprovedRewrite } = load('rewrite-with-credit.ts'); const f = fixture();
  const approval = await prepareRewrite(f.api, 'w', request());
  await assert.rejects(submitApprovedRewrite(f.api, 'w', approval, 1100), /maximum/i);
  assert.equal(f.calls.some(c => c[0] === 'quote' || c[0] === 'rewrite'), false);
});
for (const changed of [{ ceilingMilliCredits: 1300, estimateMilliCredits: 1300 }, { stateRevision: 8 }, { policy: 'new-plan' }, { model: 'other-writer' }]) {
  test(`changed rewrite binding ${Object.keys(changed).join('/')} needs a fresh estimate and explicit MAX`, async () => {
    const { prepareRewrite, submitApprovedRewrite, RewriteReviewChanged } = load('rewrite-with-credit.ts'); const f = fixture();
    const approval = await prepareRewrite(f.api, 'w', request()); f.change(changed);
    await assert.rejects(submitApprovedRewrite(f.api, 'w', approval, 1500), e => e instanceof RewriteReviewChanged && e.approval.estimate.stateRevision === (changed.stateRevision ?? 7));
    assert.equal(f.calls.some(c => c[0] === 'quote' || c[0] === 'rewrite'), false);
  });
}
test('completed cached rewrite performs no new paid quote and retains the request key', async () => {
  const { prepareRewrite, submitApprovedRewrite } = load('rewrite-with-credit.ts'); const f = fixture();
  f.change({ cached: true, estimateMilliCredits: 0, ceilingMilliCredits: 0, availableMilliCredits: 0, basis: 'completed_rewrite' });
  const approval = await prepareRewrite(f.api, 'w', request()); await submitApprovedRewrite(f.api, 'w', approval, null);
  assert.equal(f.calls.some(c => c[0] === 'quote'), false); assert.deepEqual(f.calls.find(c => c[0] === 'rewrite')[1], request());
});
test('unqualified and malformed rewrite estimates cannot become customer approvals', async () => {
  const { prepareRewrite } = load('rewrite-with-credit.ts');
  for (const changed of [{ estimateKind: undefined }, { basis: 'ordinary-writer' }, { stateRevision: undefined }, { ceilingMilliCredits: NaN }, { ceilingMilliCredits: -1 }]) {
    const f = fixture(); f.change(changed); await assert.rejects(prepareRewrite(f.api, 'w', request()), /maximum|estimate|revision/i);
    assert.equal(f.calls.some(c => c[0] === 'quote'), false);
  }
});
const radar = () => ({ paidScanAvailable: false, aiAnalysisAvailable: false, monitoringAvailable: false, consent: { sources: ['zero', 'paid'], ai: true }, sources: [{ id: 'zero', status: 'ready' }, { id: 'paid', status: 'credit_bridge_unavailable' }] });
test('server-qualified zero-cost Radar works for managed and Free with AI off', () => {
  const { radarAvailability, radarScanAvailable } = load('radar-availability.ts');
  for (const mode of ['managed_credits', 'free_preview']) {
    const usage = { billingMode: mode }, catalog = radar(), spec = { sources: ['zero'], useAi: false };
    assert.equal(radarAvailability(usage, catalog, spec, true).available, true);
    assert.equal(radarScanAvailable(usage, catalog, { ...spec, maximumUsdMicro: 0, customerCharge: 'none' }, true), true);
  }
});
test('Radar never promotes raw consent, unavailable paid sources, AI or cached catalog failure to readiness', () => {
  const { radarAvailability } = load('radar-availability.ts');
  const usage = { billingMode: 'managed_credits' }, catalog = radar();
  for (const spec of [{ sources: ['paid'], useAi: false }, { sources: ['zero'], useAi: true }, { sources: [], useAi: false }]) assert.equal(radarAvailability(usage, catalog, spec, true).available, false);
  assert.equal(radarAvailability(usage, catalog, { sources: ['zero'], useAi: false }, false).available, false);
  assert.equal(radarAvailability(usage, { ...catalog, paidScanAvailable: undefined }, { sources: ['zero'], useAi: false }, true).available, false);
});
test('stored paid, stale or unknown-cost Radar quotes remain readable but cannot start in v2', () => {
  const { radarScanAvailable } = load('radar-availability.ts'); const usage = { billingMode: 'managed_credits' }, catalog = radar();
  for (const fields of [{ maximumUsdMicro: 1 }, { customerCharge: 'credits' }, { useAi: true }, { stale: true }, { maximumUsdMicro: undefined }]) assert.equal(radarScanAvailable(usage, catalog, { sources: ['zero'], useAi: false, maximumUsdMicro: 0, customerCharge: 'none', ...fields }, true), false);
  assert.equal(radarScanAvailable({ billingMode: 'legacy_allowances' }, catalog, { sources: ['paid'], useAi: true, maximumUsdMicro: 10000, customerCharge: 'included_allowance' }, true), true);
});

test('actual Post Doctor caller stages managed rewrite approval after a real eligible check result', async () => {
  const React = require('react'); let cursor = 0; const slots = [], calls = [];
  let billingMode = 'free_preview', revision = 7, rewriteCalls = 0;
  const hooks = { ...React, useId: () => 'facts', useEffect: () => {}, useRef: value => { const i=cursor++; return slots[i] ??= {current:value}; }, useState: value => { const i=cursor++; if (!(i in slots)) slots[i]=value; return [slots[i],next=>slots[i]=typeof next==='function'?next(slots[i]):next]; } };
  const catalog = { postDoctor: true, consented: true, writer: 'selected-writer', rewriteCredits: { billingMode: 'managed_credits', available: true, estimateAvailable: true } };
  const api = { postDoctor: async () => ({ runId: 'saved-check' }), creditEstimate: async (_w,body) => { calls.push(['estimate',body]); return {...estimate(), stateRevision:revision}; }, creditQuote:async(_w,body)=>{calls.push(['quote',body]);return{quoteId:'original-quote',maxMilliCredits:body.maxMilliCredits};}, growthCatalog: async () => catalog, postDoctorRewrite: async (_w,body) => { calls.push(['rewrite',body]);rewriteCalls++; if(rewriteCalls===1)throw new Error('Lost response');revision=8;throw Object.assign(new Error('Input changed'),{status:409}); } };
  const source = path.resolve(__dirname,'../src/features/growth/post-doctor-panel.tsx'), m=new Module(source); m.paths=module.paths;
  const mocks={ react:hooks, '@tanstack/react-query':{useQueryClient:()=>({})}, '@/components/ui/button':{Button:()=>null}, '@/components/ui/textarea':{Textarea:()=>null}, '@/components/rafii':{Surface:()=>null}, '@/lib/auth/access':{checkAccess:()=>true,useWorkspaceAccess:()=>({role:'owner'})}, '@/lib/api/hooks':{useAct:()=>({}),useSnapshot:()=>({refetch:async()=>{}}),useUsage:()=>({data:{billingMode,freePreview:{postDoctor:{eligible:true,remaining:1}}},refetch:async()=>{}})}, '@/lib/workspace/provider':{useWorkspaceApi:()=>({api,workspaceId:'w'})}, './shared':{useGrowthCatalog:()=>({data:catalog,isSuccess:true,isError:false,refetch:async()=>({data:catalog,isSuccess:true,isError:false})}),CheckResult:()=>null,GrowthConsent:()=>null}, './availability':load('availability.ts'), './rewrite-with-credit':fs.existsSync(path.resolve(__dirname,'../src/features/growth/rewrite-with-credit.ts'))?load('rewrite-with-credit.ts'):{}, '@/features/agent/credit-limit':{parseCreditLimit:value=>Number(value)*1000}, './rewrite-credit-review':{RewriteCreditReview:()=>null} };
  m.require=id=>Object.hasOwn(mocks,id)?mocks[id]:require(id);
  m._compile(ts.transpileModule(fs.readFileSync(global.__task9PendingSource ?? source,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,source);
  function render(){ cursor=0; return m.exports.PostDoctorPanel({variant:{id:'v',revision:1}}); }

  let tree=render(); find(tree,n=>n.props?.['aria-label']==='Allow AI analysis of this draft').props.onChange({target:{checked:true}});
  tree=render(); await find(tree,n=>n.props?.children==='Check draft').props.onClick(); await new Promise(r=>setImmediate(r));
  billingMode='managed_credits';tree=render(); const rewrite=find(tree,n=>n.props?.children==='Rewrite and recheck');
  assert.equal(rewrite.props.disabled,false,'server-qualified managed rewrite is actionable');
  await rewrite.props.onClick(); await new Promise(r=>setImmediate(r));
  assert.deepEqual(calls.map(c=>c[0]),['estimate'],'actual caller estimates and waits; it never directly rewrites');
  tree=render(); find(tree,n=>n.props?.approval).props.onMaximum('1.2');tree=render();
  find(tree,n=>n.props?.approval).props.onApprove(); await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
  tree=render(); const reconcile=find(tree,n=>n.props?.children==='Reconcile rewrite');assert.ok(reconcile,'lost response retains the exact quoted body');
  reconcile.props.onClick();await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
  tree=render();assert.equal(find(tree,n=>n.props?.children==='Reconcile rewrite'),null,'stale reconciliation cannot reuse the old approval');
  const freshReview=find(tree,n=>n.props?.approval);assert.equal(freshReview.props.maximum,'');assert.equal(freshReview.props.approval.estimate.stateRevision,8);
  assert.equal(calls.filter(c=>c[0]==='quote').length,1,'stale reconciliation never silently buys another quote');
  assert.deepEqual(calls.filter(c=>c[0]==='rewrite').map(c=>c[1]),[calls.find(c=>c[0]==='rewrite')[1],calls.find(c=>c[0]==='rewrite')[1]]);

});
