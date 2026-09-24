const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
const filename=path.resolve(__dirname,'../src/features/agent/voice-consent.ts');const loaded=new Module(filename);
loaded._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,filename);
const {eligibleVoiceSources}=loaded.exports;
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
