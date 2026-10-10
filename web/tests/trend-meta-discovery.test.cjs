/** Synthetic wire contracts. No Meta token, provider call or model execution. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const ts=require('typescript');
function load(file,overrides={}){
  const out={exports:{}};
  const compiled=ts.transpileModule(fs.readFileSync(path.join(__dirname,'..',file),'utf8'),{
    compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  new Function('require','exports','module',compiled)((id)=>overrides[id]??require(id),out.exports,out);
  return out.exports;
}
const m=load('src/features/trends/api.ts',{
  './public-source-types':load('src/features/trends/public-source-types.ts'),
  '@/lib/coworker/trend-types':require('./trend-contract.cjs').loadTypes(),
  '@/lib/api/client':{ApiError:class extends Error{},APP_GUARD_HEADER:{'X-Rafii-App':'1'}}
});
const receipt={request_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',provider:'threads',
  selection:{query:'piano',search_type:'RECENT'},status:'queued',sample_size:null,
  earliest_source_at:null,latest_source_at:null,retrieved_at:null,
  created_at:'2026-10-10T15:00:00Z',expires_at:'2026-10-10T15:10:00Z',completeness:'unknown',coverage:'Selected public sample only.'};
test('discovery request input cannot carry provider credentials, costs or an untyped selection',()=>{
  assert.ok(m.discoveryRequestInputSchema,'typed request admission is missing');
  for(const [provider,selection] of [['threads',{query:'piano',search_type:'RECENT'}],
    ['instagram',{hashtag:'piano'}],['facebook',{reviewed_page_id:'123456'}]]){
    const input={provider,selection,idempotency_key:'synthetic-request'};
    assert.equal(m.discoveryRequestInputSchema.safeParse(input).success,true);
    for(const extra of [{token:'synthetic'},{authorization_id:receipt.request_id},{reservation_microusd:1}])
      assert.equal(m.discoveryRequestInputSchema.safeParse({...input,...extra}).success,false);
  }
  assert.equal(m.discoveryRequestInputSchema.safeParse({provider:'facebook',selection:{query:'123456'},idempotency_key:'k'}).success,false);
  for(const query of ['piano\nlesson', 'piano'+String.fromCharCode(0)+'lesson', 'piano'+String.fromCharCode(127)+'lesson', '   '])
    assert.equal(m.discoveryRequestInputSchema.safeParse({provider:'threads',selection:{query,search_type:'RECENT'},idempotency_key:'k'}).success,false);
  assert.equal(m.discoveryRequestInputSchema.safeParse({provider:'threads',selection:{query:'鋼琴 🎹',search_type:'RECENT'},idempotency_key:'k'}).success,true);
});
test('queued or unavailable receipts keep unknown counts and permit revoked selection redaction',()=>{
  assert.ok(m.discoveryReceiptSchema,'typed receipt is missing');
  assert.equal(m.discoveryReceiptSchema.parse(receipt).sample_size,null);
  assert.equal(m.discoveryReceiptSchema.safeParse({...receipt,status:'unavailable',selection:null}).success,true);
  const noExpiry={...receipt}; delete noExpiry.expires_at;
  assert.equal(m.discoveryReceiptSchema.safeParse(noExpiry).success,false);
  for(const patch of [{sample_size:-1},{sample_size:NaN},{provider:'instagram'},
    {status:'LIVE'},{status:'queued',sample_size:0},{selection:null}])
    assert.equal(m.discoveryReceiptSchema.safeParse({...receipt,...patch}).success,false,JSON.stringify(patch));
});
test('public discovery exposes separate read and explicit submit methods',()=>{
  const api=m.createTrendApi(async()=> 'synthetic-session');
  assert.equal(typeof api.discoveryRequests,'function');
  assert.equal(typeof api.submitDiscoveryRequest,'function');
});
