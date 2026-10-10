/** Synthetic contract/presentation tests only; no provider/model/browser calls. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname,'../src/features/trends/public-source-types.ts'),'utf8');
const output = {exports:{}};
new Function('require','exports','module',ts.transpileModule(source,{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}
}).outputText)(require,output.exports,output);
const m = output.exports;
const gates = {
  implemented:'VERIFIED', runtime_bound:'VERIFIED', app_reviewed:'VERIFIED',
  verified_scope_or_feature:'VERIFIED', live_read_verified:'VERIFIED',
  stored_and_processed:'VERIFIED', production_ui_verified:'UNVERIFIED'
};
const fixture = () => ({
  provider:'threads',operation:'keyword_search',label:'Threads keywords',status:'LIVE',
  authorization_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  latest_successful_read:'2026-10-09T12:00:00Z',expires_at:'2026-10-09T12:10:00Z',
  dispatch_enabled:true,coverage:'Synthetic query sample',semantic_evaluation:'Synthetic uncalled JEV',
  verification:{...gates}
});
test('seven independent source gates are required and reject invented eighth gates or numeric unknowns',()=>{
  assert.equal(m.publicSourceSchema.safeParse(fixture()).success,true);
  for(const key of Object.keys(gates)){
    const value=fixture();delete value.verification[key];
    assert.equal(m.publicSourceSchema.safeParse(value).success,false,key);
  }
  for(const verification of [{...gates,unknown_gate:'VERIFIED'},{...gates,live_read_verified:0}])
    assert.equal(m.publicSourceSchema.safeParse({...fixture(),verification}).success,false);
  const missing=fixture();delete missing.verification;
  assert.equal(m.publicSourceSchema.safeParse(missing).success,false);
});
test('cached LIVE expires without promoting unknowns or changing independent historic gates',()=>{
  assert.equal(typeof m.publicSourcePresentation,'function');
  const value=fixture(),before=structuredClone(value);
  const shown=m.publicSourcePresentation(value,true);
  assert.equal(shown.status,'AUTHORIZATION_REQUIRED');
  assert.deepEqual(shown.verification,{
    implemented:'VERIFIED',runtime_bound:'VERIFIED',app_reviewed:'VERIFIED',
    verified_scope_or_feature:'UNVERIFIED',live_read_verified:'UNVERIFIED',
    stored_and_processed:'UNVERIFIED',production_ui_verified:'UNVERIFIED'
  });
  assert.deepEqual(m.publicSourcePresentation({...value,verification:{...gates,live_read_verified:'BLOCKED'}},true)
    .verification.live_read_verified,'BLOCKED');
  assert.deepEqual(value,before);
  assert.equal(m.publicSourcePresentation(value,false).verification.production_ui_verified,'UNVERIFIED');
  const stale=m.publicSourcePresentation(value,false,true);
  assert.equal(stale.status,'STALE');
  assert.equal(stale.verification.verified_scope_or_feature,'VERIFIED','a stale read does not revoke a current grant');
  assert.equal(stale.verification.live_read_verified,'UNVERIFIED');
});
test('all seven labels and consent/source/JEV copy follow existing English or Traditional Chinese locale',()=>{
  assert.equal(typeof m.publicSourceCopy,'function');
  const en=m.publicSourceCopy('en-US'),zh=m.publicSourceCopy('zh-HK');
  assert.equal(en.title,'Public discovery sources');
  assert.equal(zh.title,'公開內容探索來源');
  assert.equal(m.publicSourceCopy('yue-HK').title,zh.title);
  assert.deepEqual(Object.keys(en.gates),[
    'implemented','runtime_bound','app_reviewed','verified_scope_or_feature','live_read_verified',
    'stored_and_processed','production_ui_verified'
  ]);
  for(const key of Object.keys(gates)) assert.match(zh.gates[key],/[一-鿿]/);
  for(const key of ['caveat','revokeConfirm','revokeError','jev']) assert.match(zh[key],/[一-鿿]/);
});
