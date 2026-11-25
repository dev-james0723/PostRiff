const { test } = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript'), Module = require('node:module');
function moduleOf(relative) {
 const file = path.resolve(__dirname, '../src/features/agent', relative); const m = new Module(file);
 m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText, file); return m.exports;
}
const policy = moduleOf('work-surface-policy.ts').workSurfacePolicy;
const recovery = moduleOf('brief-recovery.ts');
function caller(file, name, variables) {
 const filename=path.resolve(__dirname, '../src/features/agent', file);
 const source=ts.createSourceFile(filename,fs.readFileSync(filename,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 let found; function visit(n){if(ts.isFunctionDeclaration(n)&&n.name?.text===name)found=n;ts.forEachChild(n,visit);} visit(source);
 assert.ok(found, name + ' is an actual component caller');
 const code=ts.transpileModule(found.getText(source),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
 return new Function(...Object.keys(variables),code+'; return '+name+';')(...Object.values(variables));
}
test('unresolved billing and writer cost cannot authorize a v2 text task',()=>{
 assert.match(policy(undefined, undefined, false).blocked, /loading/);
 assert.match(policy({billingMode:'managed_credits',credits:{spendAvailable:true}},undefined,false).blocked,/loading/);
});
test('Home paid automation quick replies stage review instead of calling turn directly',async()=>{
 const calls=[], saved=new Map(); const usage={data:{billingMode:'managed_credits',credits:{spendAvailable:true},aiUsageExempt:false}};
 const fn=caller('home-view.tsx','answerAutomation',{
  automationReply:{workspaceId:'w',id:'c'},workspaceId:'w',canEdit:true,usage,models:{isSuccess:true},
  choice:{option:{costClass:'paid'},requestFields:{}}, workSurfacePolicy:policy,user:{id:'u'},
  turnStorageKey:recovery.turnStorageKey,decodeBriefState:recovery.decodeBriefState,encodeBrief:recovery.encodeBrief,
  sessionStorage:{getItem:k=>saved.get(k)??null,setItem:(k,v)=>saved.set(k,v)},router:{push:v=>calls.push(['navigate',v])},
  api:{turn:async()=>{calls.push(['turn']);return {runId:'r'};}},languages:{destinations:[]},voiceMode:'neutral',voiceSourceIds:[],timeZone:'UTC',
  client:{invalidateQueries:async()=>{},setQueryData:()=>{}},keys:new Proxy({},{get:()=>()=>[]}),setAutomationReply:()=>{},
  toast:Object.assign(v=>calls.push(['notice',v]),{error:v=>calls.push(['error',v])}),ApiError:Error
 });
 await fn('Draft once more');
 assert.equal(calls.some(c=>c[0]==='turn'),false,'no paid transport before review');
 assert.equal(recovery.decodeBrief(saved.get(recovery.turnStorageKey('u','w','c')),'u','w'),'Draft once more');
 saved.set(recovery.turnStorageKey('u','w','c'),recovery.encodeBrief('u','w','My unsent message'));
 await fn('Another reply');
 assert.equal(recovery.decodeBrief(saved.get(recovery.turnStorageKey('u','w','c')),'u','w'),'My unsent message','existing unsent text preserved');
});
test('Conversation paid quick replies stage their own estimate and leave existing unsent text intact',async()=>{
 let current='', limit='1.2', image=true; const calls=[];
 const fn=caller('conversation-view.tsx','sendTurn',{
  text:current,busy:false,running:false,choice:{available:true},imageRequested:false,creditMode:true,policy:{blocked:null},
  setText:next=>{current=typeof next==='function'?next(current):next},setCreditLimit:v=>limit=v,setImageRequested:v=>image=v,
  toast:Object.assign(v=>calls.push(['notice',v]),{error:v=>calls.push(['error',v])}),composer:{current:{focus:()=>{}}},requestAnimationFrame:f=>f(),
  parseSlash:()=>null,voiceLearningIntent:()=>null,languages:{selection:['LinkedIn']},creditInvalid:false,gate:{enter:()=>true,alive:()=>true,leave:()=>{}},
  setBusy:()=>{},attachmentsOn:false,turnPayload:body=>({text:body}),submitConversationTurn:async()=>{calls.push(['turn']);return null;},api:{},workspaceId:'w',conversationId:'c',maximum:1200
 });
 await fn('A paid quick reply');
 assert.equal(calls.some(c=>c[0]==='turn'),false,'reply must obtain its own visible estimate');
 assert.equal(current,'A paid quick reply');assert.equal(limit,'');assert.equal(image,false);
 const preserved=caller('conversation-view.tsx','sendTurn',{
  text:'My unsent message',busy:false,running:false,choice:{available:true},imageRequested:false,creditMode:true,policy:{blocked:null},
  setText:()=>assert.fail('unsent text overwritten'),toast:Object.assign(()=>{},{error:()=>{}}),parseSlash:()=>null,
 });
 await preserved('Another reply');
});
