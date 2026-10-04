/** Synthetic, no-egress tests. --fixtures exports intercepted browser route data.
 * Positive qualification here is executable fixture coverage, never a real cohort.
 * Parent browser harness: const {analysisFixtures}=require('./visual-analysis.test.cjs');
 * const a=analysisFixtures({workspace:workspaceId, trend:f.trend});
 * GET opportunities/whitespace => freshAnalysisEnvelope(a.whitespace);
 * GET :trend/forecast => freshAnalysisEnvelope(a.forecast);
 * GET :trend (both receipt-check reads) => freshAnalysisEnvelope(a.detail). Set the two feature flags true.
 * Assert no forecast GET until checking "Show stored forecast". All-platform view
 * shows numeric table; any platform selection abstains (wire has no platform field).
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadTypes, exportSchema } = require('./trend-contract.cjs');
const { fixtures } = require('./trend-fixtures.cjs');
const root = path.resolve(__dirname, '../..');
const types = loadTypes();
const clone = (v) => structuredClone(v);
const DEMO = 'Demo data: synthetic Python projection; no actual qualified cohort, provider, model or database execution.';
const python = String.raw`
import json,sys,re
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
params=json.load(sys.stdin)
def instant(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def shift(value,delta):
 if isinstance(value,dict):return {k:shift(v,delta) for k,v in value.items()}
 if isinstance(value,list):return [shift(v,delta) for v in value]
 if isinstance(value,str) and re.match(r'^\d{4}-\d\d-\d\dT',value):return (instant(value)+delta).isoformat()
 return value
def replace(value,mapping):
 if isinstance(value,dict):return {k:replace(v,mapping) for k,v in value.items()}
 if isinstance(value,list):return [replace(v,mapping) for v in value]
 return mapping.get(value,value) if isinstance(value,str) else value
with patch('socket.create_connection',side_effect=AssertionError('egress forbidden')),patch('socket.socket.connect',side_effect=AssertionError('egress forbidden')),patch('socket.getaddrinfo',side_effect=AssertionError('egress forbidden')),patch('urllib.request.urlopen',side_effect=AssertionError('egress forbidden')),patch('psycopg.connect',side_effect=AssertionError('DB forbidden')):
 from test_trend_forecast import Forecast
 from test_trend_whitespace_admission import fixture,assess
 from postriff_phase2.growth.trends import forecast,whitespace_admission
 from postriff_phase2.growth.trends.service import project_advanced,TrendService
 now=instant(params['as_of'])-timedelta(seconds=2)
 p,_=fixture()
 p=replace(p,{p['workspace_id']:params['workspace'],p['trend_id']:params['trend_id'],p['receipt_id']:params['receipt_id']})
 p=shift(p,now-instant(p['now']))
 facts=whitespace_admission.workspace_facts(p['state'])
 for review in p['reviews'].values():review['payload'].update(context_digest=facts['context_digest'],facts_digest=facts['facts_digest'])
 def whitespace_projection(args):
  r=assess(args)
  r.update(opportunity_refs=[],source_decision_cutoff=args['inputs']['common']['decision_cutoff'],computed_at=args['now'])
  return project_advanced('whitespace',r)
 admitted=whitespace_projection(p)
 p.update(reviews={},selected=[],semantic_bindings=[])
 proposed=whitespace_projection(p)
 case=Forecast();case.setUp()
 try:
  sample=case.series();sample=shift(sample,now-instant(sample['decision_cutoff']))
  sample['scope_key']='workspace:'+params['workspace']
  for source in sample['sources']:source['scope_key']=sample['scope_key'];source['expires_at']=(now+timedelta(days=2)).isoformat()
  qualified=case.qualification(sample)
  prediction=forecast.predict_candidates(qualified)
  projection=forecast.to_stored_projection(prediction,qualification_payload=qualified)
  assert projection['payload']['state']=='qualified'
  saved={'object_id':'synthetic-forecast','revision':1,'expires_at':prediction['horizon_end'],
    'method_bundle':{'method_id':'trend.forecast.admission','version':'synthetic-fixture-only'},'payload':projection['payload']}
  wire=TrendService._forecast_wire(saved)
  print(json.dumps({'whitespace':admitted,'proposed':proposed,'forecast':wire}))
 finally:case.doCleanups()
`;
function analysisFixtures({ workspace = 'synthetic-workspace', trend } = {}) {
  const base = fixtures();
  trend = clone(trend ?? base.trend);
  const asOf = new Date().toISOString();
  const localPython = path.join(root, '.venv/bin/python');
  // CI installs the pinned dependencies into setup-python's PATH interpreter.
  // An explicit override remains authoritative; a missing one fails below.
  const executable = process.env.TREND_VISUAL_TEST_PYTHON ||
    (fs.existsSync(localPython) ? localPython : 'python3');
  const result = spawnSync(executable, ['-c', python], { cwd: root, encoding: 'utf8',
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONPATH: `${root}/src:${root}/tests` },
    input: JSON.stringify({ workspace, trend_id: trend.id, receipt_id: trend.trust_receipt_id, as_of: asOf }),
    timeout: 30_000, maxBuffer: 2_000_000 });
  assert.equal(result.status, 0, `Actual Python projection unavailable: ${result.stderr || result.error}`);
  const raw = JSON.parse(result.stdout);
  trend.limitations = [...trend.limitations, DEMO];
  const envelope = (data) => ({ schema_version: '1.0', request_id: 'synthetic-visual-analysis', as_of: asOf,
    data, coverage: clone(trend.coverage), limitations: [DEMO], execution_state: 'stored_result', next_cursor: null });
  const whitespace = types.whitespaceResponseSchema.parse(envelope([raw.whitespace]));
  const proposed = types.whitespaceResponseSchema.parse(envelope([raw.proposed]));
  const forecast = types.forecastResponseSchema.parse(envelope(raw.forecast));
  const detail = types.envelopeSchema(types.trendSchema).parse(envelope(trend));
  const bound = { response: forecast, binding: { workspace_id: workspace, trend_id: trend.id,
    trust_receipt_id: trend.trust_receipt_id, checked_before: asOf, checked_after: asOf,
    expires_at: new Date(Math.min(Date.parse(trend.expires_at), Date.parse(forecast.data.expires_at))).toISOString() } };
  return { workspace, trend, whitespace, proposed, forecast, detail, bound, flags: base.flags, provenance: DEMO };
}
// Refresh read time only. Source cutoff, analysis/issuance, expiry and proof stay fixed.
function freshAnalysisEnvelope(envelope, now = Date.now()) {
  return { ...clone(envelope), as_of: new Date(now).toISOString() };
}
module.exports = { analysisFixtures, freshAnalysisEnvelope };

if (require.main === module && process.argv.includes('--fixtures')) {
  process.stdout.write(JSON.stringify(analysisFixtures(), null, 2) + '\n');
} else if (require.main === module) {
  const { test } = require('node:test');
  class ApiError extends Error { constructor(message, status, code) { super(message); this.status=status; this.code=code; } }
  let context, queryResult, requested = false;
  const queryCalls = [];
  const hooks = {
    useTrendContext: () => context,
    useExpired: (value) => !value || Date.parse(value) <= Date.now(),
    useTrendQuery: (key, read, enabled, flag) => { queryCalls.push({key,read,enabled,flag}); return queryResult; }
  };
  function load(file, extra = {}) {
    const source = ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }
    }).outputText;
    const compiledModule = { exports: {} };
    const modules = { '@/lib/coworker/trend-types': types,
      '@/lib/api/client': { ApiError, APP_GUARD_HEADER: { 'X-PostRiff-App': 'postriff-web' } },
      './hooks': hooks,
      './present': { words: (v) => v.replaceAll('_', ' '), DemoNotice: ({limitations}) => limitations.some(v=>v.startsWith('Demo data:')) ? React.createElement('p', {}, DEMO) : null },
      react: { ...React, useState: () => [requested, (v) => {requested=v;}] }, ...extra };
    new Function('require', 'exports', 'module', source)((id) => id in modules ? modules[id] : require(id), compiledModule.exports, compiledModule);
    return compiledModule.exports;
  }
  const panel = load('web/src/features/trends/visual-analysis-panels.tsx');
  const { createTrendApi } = load('web/src/features/trends/api.ts');
  const f = analysisFixtures();
  const now = Date.parse(f.forecast.as_of) + 3000;
  const reset = (data, flags=f.flags) => { context={w:f.workspace,flags,enabled:true};queryResult={data,isFetching:false,isError:false};requested=false;queryCalls.length=0; };
  const render = (Component, platform='') => renderToStaticMarkup(React.createElement(Component,{trend:f.trend,platform}));
  test('actual Python projections: reviewed whitespace, proposed whitespace and synthetic qualified forecast parse', () => {
    assert.equal(f.whitespace.data[0].state,'admitted');
    assert.equal(f.proposed.data[0].state,'review_required');
    assert.equal(f.proposed.data[0].opportunities.length,0);
    assert.equal(f.forecast.data.qualification.paired_count,10);
    assert.match(f.provenance,/synthetic/);
  });
  test('browser fixture refreshes only stored read time and preserves source timestamps', () => {
    const later=freshAnalysisEnvelope(f.forecast, Date.parse(f.forecast.as_of)+60_000);
    assert.notEqual(later.as_of,f.forecast.as_of);assert.deepEqual(later.data,f.forecast.data);
    const whitespace=freshAnalysisEnvelope(f.whitespace, Date.parse(f.whitespace.as_of)+60_000);
    assert.deepEqual(whitespace.data,f.whitespace.data);
  });
  test('generated canonical schema agrees exactly', () => {
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'docs/design/social-trend-intelligence/api.schema.json'))),exportSchema());
  });
  test('new schemas reject extra, private, unbounded and falsely qualified fields', () => {
    for(const mutate of [x=>x.extra=true,x=>x.data[0]['_admission_binding']={},x=>x.data[0].semantic_qualification='qualified',
      x=>x.data[0].claim_scope='global',x=>x.data[0].gaps[0].summary='x'.repeat(2001),
      x=>x.data=Array(21).fill(x.data[0]),x=>x.coverage.sources[0].secret='private']) {
      const x=clone(f.whitespace);mutate(x);assert.equal(types.whitespaceResponseSchema.safeParse(x).success,false);
    }
    for(const mutate of [x=>x.state='experimental',x=>x.forecast_wording_enabled=false,x=>x.admission={},
      x=>x.target.population='platform_wide',x=>x.target.platform='bluesky',x=>x.predictions[0].point=Infinity,
      x=>x.qualification.gate.rights_verified=false,x=>x.method_bundle.version='future',x=>x.predictions.push(x.predictions[0])]) {
      const x=clone(f.forecast.data);mutate(x);assert.equal(types.forecastSchema.safeParse(x).success,false);
    }
  });
  test('whitespace rejects incoherent sample denominators, crossrefs, states, facts and timestamps', () => {
    for(const mutate of [x=>x.opportunities[0].supply_search_scope.retrieval_coverage=.9,
      x=>x.opportunities[0].supply_search_scope.evidence_refs.push('foreign'),
      x=>x.opportunities[0].credibility.workspace_id='foreign',x=>x.opportunities[0].credibility.approved_fact_refs=[],
      x=>x.opportunities[0].demand_evidence_refs=['foreign','other'],x=>x.opportunities[0].gap_type='unanswered_question',
      x=>x.gaps[0].state='review_required',x=>x.gaps.push(x.gaps[0]),x=>x.computed_at=x.expires_at]) {
      const x=clone(f.whitespace.data[0]);mutate(x);assert.equal(types.whitespaceSchema.safeParse(x).success,false);
    }
  });
  test('forecast rejects crossed intervals, insufficient calibration, target mismatch and future chronology', () => {
    for(const mutate of [x=>x.predictions[0].quantiles['0.1']=9999,x=>x.qualification.paired_count=2,
      x=>x.qualification.metrics.local_linear_count.interval_coverage=0,
      x=>x.qualification.gate.dataset_digest='0'.repeat(64),x=>x.target.horizon_steps=2,
      x=>x.training_cutoff=x.horizon_end,x=>x.structural_break=true,x=>x.qualification.improvement_interval.lower=0]) {
      const x=clone(f.forecast.data);mutate(x);assert.equal(types.forecastSchema.safeParse(x).success,false);
    }
  });
  test('whitespace selection requires exact workspace/trend/receipt/platform and current read/retention', () => {
    assert.equal(panel.selectWhitespace(f.whitespace,f.trend,f.workspace,'bluesky',now).gaps.length,1);
    assert.equal(panel.selectWhitespace(f.whitespace,f.trend,f.workspace,'Bluesky',now),null);
    assert.equal(panel.selectWhitespace(f.whitespace,f.trend,'foreign','',now),null);
    for(const mutation of [{id:'foreign'},{trust_receipt_id:'other'},{verification_state:'policy_revoked'},{expires_at:new Date(now).toISOString()}])
      assert.equal(panel.selectWhitespace(f.whitespace,{...f.trend,...mutation},f.workspace,'',now),null);
    const x=clone(f.whitespace);x.data.push(x.data[0]);assert.equal(panel.selectWhitespace(x,f.trend,f.workspace,'',now),null);
    assert.equal(panel.selectWhitespace(f.whitespace,f.trend,f.workspace,'',now+30_000),null);
  });
  test('all feature flags default off, including trust receipts', () => {
    for(const kind of ['WHITESPACE','FORECASTS']) {
      assert.equal(panel.analysisEnabled({},kind),false);assert.equal(panel.analysisEnabled(f.flags,kind),true);
      for(const key of ['RAFII_TREND_INTELLIGENCE_ENABLED','RAFII_TREND_RADAR_ENABLED','RAFII_TREND_TRUST_RECEIPTS_ENABLED',`RAFII_TREND_${kind}_ENABLED`])
        assert.equal(panel.analysisEnabled({...f.flags,[key]:false},kind),false);
    }
  });
  test('available whitespace panel displays actual sample, contribution, times and authority limits', () => {
    reset(f.whitespace);const html=render(panel.WhitespacePanel);
    for(const value of ['Supported in this sample','Use the owned notebook','Source decision cutoff','Analysis computed','Sample retrieval coverage','semantic qualification remain unknown','publishing approval remain separate','Demo data:'])assert.ok(html.includes(value),value);
    assert.match(html, /role="region"[^>]*aria-label="Creative whitespace"/);
    assert.ok(html.includes('<table'));assert.equal(queryCalls[0].enabled,true);
  });
  test('proposed panel preserves review reasons and never presents an admitted contribution', () => {
    reset(f.proposed);const html=render(panel.WhitespacePanel);
    assert.match(html,/Proposed · review required/);assert.match(html,/current candidate review required/);
    assert.doesNotMatch(html,/Use the owned notebook|Supported in this sample/);
  });
  test('whitespace empty, error, loading, stale and disabled states remove stale claims', () => {
    for(const state of ['empty','error','loading','stale','disabled','wrong-platform']) {
      const x=clone(f.whitespace);if(state==='empty')x.data=[];if(state==='stale')x.as_of=new Date(Date.now()-31_000).toISOString();
      reset(x,state==='disabled'?{}:f.flags);queryResult.isError=state==='error';queryResult.isFetching=state==='loading';
      const html=render(panel.WhitespacePanel,state==='wrong-platform'?'tiktok':'');
      assert.match(html,/Unknown/);assert.doesNotMatch(html,/Use the owned notebook|<table/);
    }
  });
  test('partial and long multilingual content stay text with explicit limitations', () => {
    const x=clone(f.whitespace);x.execution_state='partial';x.data[0].truncated=true;x.data[0].gaps[0].summary='粵語 · <script>not executable</script> '.repeat(20);
    reset(x);const html=render(panel.WhitespacePanel);assert.match(html,/Partial coverage/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
  });
  test('forecast never queries before toggle, when disabled, or for an unspecified platform binding', () => {
    reset(f.bound);render(panel.ForecastPanel);assert.equal(queryCalls.at(-1).enabled,false);
    requested=true;const html=render(panel.ForecastPanel,'bluesky');assert.equal(queryCalls.at(-1).enabled,false);assert.match(html,/does not identify a target platform/);
    reset(f.bound,{});requested=true;render(panel.ForecastPanel);assert.equal(queryCalls.at(-1).enabled,false);
  });
  test('synthetic qualified forecast toggle renders a numeric table, calibration, version and real horizon only', () => {
    reset(f.bound);requested=true;const html=render(panel.ForecastPanel);
    assert.equal(queryCalls.at(-1).enabled,true);
    for(const value of ['Point estimate','10th percentile','90th percentile','forecast_v2','10 paired predictions','Source training cutoff','Forecast target window','Receipt confirmed','synthetic'])assert.ok(html.includes(value),value);
    assert.doesNotMatch(html,/<svg|<path|<canvas/);
  });
  test('forecast binding change, stale read, expiry, missing qualification and errors suppress numeric values', (t) => {
    // The selector and rendered component must evaluate the same instant;
    // process scheduling must not make an expired fixture future-dated.
    t.mock.method(Date, 'now', () => now);
    for(const mutate of [x=>x.binding.trust_receipt_id='other',x=>x.binding.workspace_id='other',
      x=>x.response.data.scope_key='workspace:other',x=>x.response.as_of=new Date(now-31_000).toISOString(),
      x=>x.binding.expires_at=new Date(now-1000).toISOString(),x=>delete x.response.data.qualification]) {
      const x=clone(f.bound);mutate(x);assert.equal(panel.selectForecast(x,f.trend,f.workspace,'',now),null);
      reset(x);requested=true;assert.doesNotMatch(render(panel.ForecastPanel),/Point estimate/);
    }
    for(const state of ['error','loading']) {reset(f.bound);requested=true;queryResult.isError=state==='error';queryResult.isFetching=state==='loading';assert.doesNotMatch(render(panel.ForecastPanel),/Point estimate/);}
  });
  test('stored APIs encode IDs and use GET/no-store/auth/abort only; invalid forecast rejects', async () => {
    const original=global.fetch;const calls=[];const abort=new AbortController();
    global.fetch=async(url,init)=>{calls.push({url,init});return {ok:true,json:async()=>url.includes('whitespace')?f.whitespace:f.forecast};};
    try {
      const api=createTrendApi(async()=> 'synthetic-token');await api.whitespace('workspace /',abort.signal);await api.forecast('workspace /','trend /',abort.signal);
      assert.match(calls[0].url,/workspace%20%2F\/coworker\/trends\/opportunities\/whitespace$/);
      assert.match(calls[1].url,/trend%20%2F\/forecast$/);
      for(const {init} of calls){assert.equal(init.method,'GET');assert.equal(init.cache,'no-store');assert.equal(init.signal,abort.signal);assert.equal(init.body,undefined);assert.equal(init.headers.Authorization,'Bearer synthetic-token');}
      global.fetch=async()=>({ok:true,json:async()=>({...f.forecast,data:{...f.forecast.data,state:'unqualified'}})});
      await assert.rejects(api.forecast('w','t'),e=>e.code==='invalid_response');
    } finally {global.fetch=original;}
  });
  test('forecast bracket reads use actual endpoint and detect a changed receipt before displaying', async () => {
    const calls=[];const api={detail:async()=>{calls.push('detail');return clone(f.detail);},forecast:async()=>{calls.push('forecast');return clone(f.forecast);}};
    const read=await panel.readBoundForecast(api,f.workspace,f.trend,new AbortController().signal);
    assert.deepEqual(calls,['detail','forecast','detail']);assert.ok(panel.selectForecast(read,f.trend,f.workspace,'',Date.now()));
    let i=0;api.detail=async()=>{i++;const d=clone(f.detail);if(i===2)d.data.trust_receipt_id='changed';return d;};
    await assert.rejects(panel.readBoundForecast(api,f.workspace,f.trend,new AbortController().signal),e=>e.code==='revision_conflict');
  });
  function outsideDetails(html) {
    let depth=0, visible='';
    for(const token of html.split(/(<[^>]+>)/g)) {
      if(/^<details(?:\s|>)/.test(token))depth++;
      else if(token==='</details>')depth--;
      else if(depth===0)visible+=token;
    }
    assert.equal(depth,0,'balanced native disclosures');return visible;
  }
  test('whitespace disclosure preserves every field while keeping summary and contribution visible', () => {
    reset(f.whitespace);const html=render(panel.WhitespacePanel),visible=outsideDetails(html);
    assert.match(html,/>Evidence and comparison details<\/summary>/);
    assert.doesNotMatch(html,/<details[^>]*\sopen(?:=|\s|>)/);
    for(const text of ['Supported in this sample',f.whitespace.data[0].gaps[0].summary,'Proposed contribution','Use the owned notebook','Based on the posts observed in this sample'])assert.ok(visible.includes(text),text);
    for(const text of ['Observed original posts','Known creators','Sample retrieval coverage','Demand references','Approved workspace fact references','Disconfirming evidence','Source decision cutoff','Analysis computed','Current stored read','Evidence expires','semantic qualification']) {
      assert.ok(html.includes(text),text+' retained');assert.ok(!visible.includes(text),text+' disclosed');
    }
    reset(f.proposed);const proposed=render(panel.WhitespacePanel);
    assert.match(outsideDetails(proposed),/Proposed · review required/);
    assert.match(proposed,/current candidate review required/);
  });
  test('forecast disclosure keeps estimates and target window visible while preserving detailed metadata', () => {
    reset(f.bound);requested=true;const html=render(panel.ForecastPanel),visible=outsideDetails(html);
    for(const text of ['Point estimate','10th percentile','50th percentile','90th percentile','Forecast target window',f.forecast.data.target_start,f.forecast.data.horizon_end])assert.ok(visible.includes(text),text);
    for(const text of ['Observed-sample frame','Source training cutoff','Forecast issued','Evidence expires','Method / feature version','Admission version','10 paired predictions','Qualification digest','Current analysis and rights read','Receipt confirmed']) {
      assert.ok(html.includes(text),text+' retained');assert.ok(!visible.includes(text),text+' disclosed');
    }
    assert.doesNotMatch(html,/<details[^>]*\sopen(?:=|\s|>)/);
  });
  test('no model/provider/mutation actions or observed timeline rewrites in panel source', () => {
    const source=fs.readFileSync(path.join(root,'web/src/features/trends/visual-analysis-panels.tsx'),'utf8');
    assert.doesNotMatch(source,/api\.(acceptOpportunity|runLab|recordExposure|watch|recordMetricChoice)|observed\.timeline\s*=/);
    assert.equal(source.includes('readBoundForecast'),true);
  });
}
