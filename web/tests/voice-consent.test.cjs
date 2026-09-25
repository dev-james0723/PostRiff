const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
const filename=path.resolve(__dirname,'../src/features/agent/voice-consent.ts');const loaded=new Module(filename);
loaded._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,filename);
const {eligibleVoiceSources,effectiveVoiceMode}=loaded.exports;
test('changing writer never transfers exact sample consent to a different cloud model or CLI',()=>{
 const source={id:'sample',kind:'voice_sample',active:true,selected:true,useGrants:[{purpose:'generation',route:'cloud:gateway:model-a'},{purpose:'analysis',route:'cloud:gateway:model-b'}]};
 const model={qualified:true,voiceRoute:'cloud:gateway:model-a'};
 assert.deepEqual(eligibleVoiceSources([source],model),['sample']);
 for (const route of ['cloud:gateway:model-b','cloud:claude-code:sonnet','local-cli']) assert.deepEqual(eligibleVoiceSources([source],{...model,voiceRoute:route}),[]);
 assert.deepEqual(eligibleVoiceSources([{...source,active:false}],model),[]);
 assert.deepEqual(eligibleVoiceSources([{...source,useGrants:[]}],model),[]);
 assert.deepEqual(eligibleVoiceSources([source],undefined),[]);
 assert.deepEqual(eligibleVoiceSources([source],{...model,qualified:false}),[]);
});
test('one writing grant for every Rafii AI writer model covers exactly the models the server puts in that class',()=>{
 const any='cloud:vercel-ai-gateway:*';
 const source={id:'sample',kind:'voice_sample',active:true,selected:true,useGrants:[{purpose:'generation',route:any}]};
 const sol={qualified:true,voiceRoute:'cloud:vercel-ai-gateway:openai/gpt-6-sol',voiceRouteClass:any};
 assert.deepEqual(eligibleVoiceSources([source],sol),['sample']);
 assert.deepEqual(eligibleVoiceSources([source],{...sol,voiceRoute:'cloud:vercel-ai-gateway:anthropic/claude-sonnet-5'}),['sample']);
 for (const model of [{qualified:true,voiceRoute:'cloud:claude-code:sonnet'},{qualified:true,voiceRoute:'local-cli',voiceRouteClass:null},{...sol,qualified:false}]) assert.deepEqual(eligibleVoiceSources([source],model),[]);
 assert.deepEqual(eligibleVoiceSources([{...source,useGrants:[{purpose:'analysis',route:any}]}],sol),[]);
});
test('drafts write like the author by default only when this writer may read an approved sample',()=>{
 assert.equal(effectiveVoiceMode(null,2),'personalized');
 assert.equal(effectiveVoiceMode('neutral',2),'neutral','the person can still choose neutral');
 assert.equal(effectiveVoiceMode(null,0),'neutral');
 assert.equal(effectiveVoiceMode('personalized',0),'neutral','no eligible sample for this writer means neutral');
});
