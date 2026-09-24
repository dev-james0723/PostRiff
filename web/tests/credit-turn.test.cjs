const {test}=require('node:test'); const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
function load(){
 const file=path.resolve(__dirname,'../src/features/agent/credit-turn.ts');
 assert.ok(fs.existsSync(file),'conversation credit submission must be implemented');
 const m=new Module(file);m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,file);return m.exports.submitConversationTurn;
}
function fixture(){
 const calls=[];const api={snapshot:async(w)=>{calls.push(['snapshot',w]);return {revision:7};},creditQuote:async(w,b)=>{calls.push(['quote',w,b]);return {quoteId:'approved-quote'};},turn:async(w,c,b)=>{calls.push(['turn',w,c,b]);return {runId:'run-two',status:'completed'};}};
 return {api,calls};
}
const base={workspaceId:'workspace-a',conversationId:'conversation-a',request:{text:'Refine it.',model:'cloud/model',destinations:[{platform:'Threads',channelId:'account-a',language:'en-US'}]}};
test('follow-up binds a credit approval to this conversation and exact request',async()=>{
 const {api,calls}=fixture();const result=await load()({...base,api,maxMilliCredits:12000});
 assert.equal(result.runId,'run-two');assert.deepEqual(calls.map(c=>c[0]),['snapshot','quote','turn']);
 assert.equal(calls[1][2].operation,'turn');assert.equal(calls[1][2].conversationId,'conversation-a');
 assert.equal(calls[1][2].expectedRevision,7);assert.equal(calls[2][3].creditQuoteId,'approved-quote');
 assert.equal(calls[2][3].research,false);assert.equal(base.request.research,undefined);
 assert.equal(calls[2][3].destinations[0].channelId,'account-a');
});
test('legacy and own-provider follow-ups do not create a cloud-credit approval',async()=>{
 const {api,calls}=fixture();await load()({...base,api,maxMilliCredits:null});assert.deepEqual(calls.map(c=>c[0]),['turn']);
 assert.equal(calls[0][3].research,undefined);
});
test('a rejected credit approval never dispatches a model turn',async()=>{
 const {api,calls}=fixture();api.creditQuote=async()=>{throw Error('Limit exceeded');};
 await assert.rejects(load()({...base,api,maxMilliCredits:12000}),/Limit exceeded/);assert.equal(calls.some(c=>c[0]==='turn'),false);
});
test('leaving the conversation while approving does not submit into the old view',async()=>{
 const {api,calls}=fixture();let current=true;
 api.creditQuote=async()=>{current=false;return {quoteId:'approved-quote'};};
 assert.equal(await load()({...base,api,maxMilliCredits:12000,isCurrent:()=>current}),null);
 assert.equal(calls.some(c=>c[0]==='turn'),false);
});
test('invalid limits and unapproved media/research are rejected before transport',async()=>{
 for(const value of [0,-1,NaN,1.2,100000001]){
  const {api,calls}=fixture();await assert.rejects(load()({...base,api,maxMilliCredits:value}));assert.deepEqual(calls,[]);
 }
 for(const request of [{...base.request,research:true},{...base.request,imageGeneration:{enabled:true}}]){
  const {api,calls}=fixture();await assert.rejects(load()({...base,request,api,maxMilliCredits:12000}));assert.deepEqual(calls,[]);
 }
});
test('the conversation uses the credit flow and immediate submission guard',()=>{
 const source=fs.readFileSync(path.resolve(__dirname,'../src/features/agent/conversation-view.tsx'),'utf8');
 assert.ok(source.includes('submitConversationTurn'),'follow-up should not bypass credits');
 assert.ok(source.includes('createSubmissionGate'),'same-tick duplicate submissions need a lock');
 assert.ok(source.includes('CreditLimitField'),'credit users need a visible approval limit');
});

test('the preserved v9 homepage binds its own quote before quick-start',async()=>{
 const file=path.resolve(__dirname,'../src/features/agent/credit-turn.ts');const m=new Module(file);
 m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,file);
 assert.equal(typeof m.exports.submitQuickStart,'function');const calls=[];
 const api={creditQuote:async(w,b)=>{calls.push(b);return {quoteId:'home-quote'};},quickStart:async(w,r,b)=>{calls.push(b);return {runId:'home-run'};}};
 await m.exports.submitQuickStart({api,workspaceId:'workspace-a',expectedRevision:9,request:base.request,maxMilliCredits:20000});
 assert.equal(calls[0].operation,'quick-start');assert.equal(calls[0].expectedRevision,9);
 assert.equal(calls[1].creditQuoteId,'home-quote');assert.equal(calls[1].research,false);
});

function apiError(status,code){const e=new Error('upstream');e.name='ApiError';e.status=status;e.code=code;return e;}
function quickModule(){const file=path.resolve(__dirname,'../src/features/agent/credit-turn.ts');const m=new Module(file);m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,file);return m.exports;}
const keyed={...base.request,idempotencyKey:'same-key'};
test('a lost response is resent with the identical keyed request, never re-approved',async(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});
 const calls=[];let failures=2;
 const api={creditQuote:async(w,b)=>{calls.push(['quote',b]);return {quoteId:'q-1'};},quickStart:async(w,r,b)=>{calls.push(['quick',structuredClone(b)]);if(failures-->0)throw failures?new TypeError('Failed to fetch'):apiError(504);return {runId:'run-1',status:'running'};}};
 const pending=quickModule().submitQuickStart({api,workspaceId:'w',expectedRevision:3,request:keyed,maxMilliCredits:5000});
 for(let i=0;i<5;i++){await Promise.resolve();t.mock.timers.tick(5000);await new Promise(r=>setImmediate(r));}
 const result=await pending;
 assert.equal(result.runId,'run-1');
 assert.deepEqual(calls.map(c=>c[0]),['quote','quick','quick','quick']);
 const sent=calls.filter(c=>c[0]==='quick').map(c=>JSON.stringify(c[1]));
 assert.equal(new Set(sent).size,1,'every resend carries the same key, quote and body');
});
test('an answer from the application is final: no resend of a refused or failed request',async()=>{
 for(const error of [apiError(502,'bad_gateway'),apiError(409,'idempotency_conflict'),apiError(402,'payment_required')]){
  const calls=[];const api={creditQuote:async()=>({quoteId:'q'}),quickStart:async()=>{calls.push(1);throw error;}};
  await assert.rejects(quickModule().submitQuickStart({api,workspaceId:'w',expectedRevision:3,request:keyed,maxMilliCredits:5000}));
  assert.equal(calls.length,1,error.code);
 }
});
test('an unkeyed request is never resent',async()=>{
 const calls=[];const api={creditQuote:async()=>({quoteId:'q'}),quickStart:async()=>{calls.push(1);throw new TypeError('Failed to fetch');}};
 await assert.rejects(quickModule().submitQuickStart({api,workspaceId:'w',expectedRevision:3,request:base.request,maxMilliCredits:5000}),/Failed to fetch/);
 assert.equal(calls.length,1);
});
test('when resends are exhausted the person is told the request may still be running',async(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});
 const api={creditQuote:async()=>({quoteId:'q'}),quickStart:async()=>{throw new TypeError('Failed to fetch');}};
 const pending=quickModule().submitQuickStart({api,workspaceId:'w',expectedRevision:3,request:keyed,maxMilliCredits:5000});
 const outcome=assert.rejects(pending,/may still be running/);
 for(let i=0;i<5;i++){await Promise.resolve();t.mock.timers.tick(5000);await new Promise(r=>setImmediate(r));}
 await outcome;
});
