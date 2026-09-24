const {test}=require('node:test'); const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
const filename=path.resolve(__dirname,'../src/features/agent/plan.ts');const loaded=new Module(filename);
loaded.require=(id)=>id==='@/lib/locales'?{locales:{same:(a,b)=>a===b}}:require(id);
loaded._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,filename);
const {variantForRow}=loaded.exports;
const variant=(id,account,run='run-current')=>({id,channelId:account,platform:'Instagram',language:'en-US',provenance:{runId:run}});
test('review matches the requested account, not the first platform match',()=>{
 const state={variants:[variant('a','account-a'),variant('b','account-b')]};
 assert.equal(variantForRow(state,{runId:'run-current'},{platform:'Instagram',language:'en-US',channelId:'account-b'})?.id,'b');
});
test('review never borrows a draft from a different generation',()=>{
 assert.equal(variantForRow({variants:[variant('old','account-a','old-run')]},{runId:'run-current'},{platform:'Instagram',language:'en-US',channelId:'account-a'}),undefined);
});
test('review refuses a different account even for the same platform',()=>{
 assert.equal(variantForRow({variants:[variant('a','account-a')]},{runId:'run-current'},{platform:'Instagram',language:'en-US',channelId:'account-b'}),undefined);
});
test('one legacy platform draft can still be assigned explicitly',()=>{
 assert.equal(variantForRow({variants:[variant('legacy',undefined)]},{runId:'run-current'},{platform:'Instagram',language:'en-US',channelId:'account-a'})?.id,'legacy');
});
