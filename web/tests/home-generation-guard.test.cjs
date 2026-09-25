const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
function helper(){const file=path.resolve(__dirname,'../src/features/agent/home/draft-edit-guard.ts');assert.ok(fs.existsSync(file),'Save must check the text on which an edit was based');const m=new Module(file);m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,file);return m.exports.checkEditBase;}
test('concurrent changes are not overwritten by locally edited captions',()=>{
 const check=helper();assert.throws(()=>check('original','changed elsewhere','my edit'),/changed/);
 assert.doesNotThrow(()=>check('original','original','my edit'));
 assert.doesNotThrow(()=>check('original','my edit','my edit'));
});
test('homepage results can reload their persisted run and current saved text',()=>{
 const source=fs.readFileSync(path.resolve(__dirname,'../src/features/agent/home/use-home-generation.ts'),'utf8');
 assert.ok(source.includes('restoreRunId'),'reload uses the run ID in the URL');
 assert.ok(source.includes('buildItems<RunVariant>('),'saved user edits remain visible after reload (behaviour: home-generation-items.test.cjs)');
 assert.ok(source.includes('submitQuickStart'),'home uses the approved credit route');
});
