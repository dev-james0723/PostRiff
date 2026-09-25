const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
function load() {
 const name=path.resolve(__dirname,'../src/features/agent/submission-gate.ts');
 assert.ok(fs.existsSync(name),'submission gate must exist');
 const m=new Module(name);m._compile(ts.transpileModule(fs.readFileSync(name,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,name);return m.exports;
}
test('duplicate clicks and keyboard submissions acquire only one slot',()=>{
 const gate=load().createSubmissionGate();gate.activate();
 assert.equal(gate.enter(),true);assert.equal(gate.enter(),false);
 gate.leave();assert.equal(gate.enter(),true);
});
test('Strict Mode cleanup and remount do not permanently deactivate submission',()=>{
 const gate=load().createSubmissionGate();gate.activate();gate.dispose();
 assert.equal(gate.enter(),false);gate.activate();assert.equal(gate.enter(),true);
});
test('disposed work cannot be accepted into another view',()=>{
 const gate=load().createSubmissionGate();gate.activate();gate.enter();gate.dispose();
 assert.equal(gate.alive(),false);gate.leave();assert.equal(gate.enter(),false);
});
