const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
function parse(value){
 const file=path.resolve(__dirname,'../src/features/agent/credit-limit.ts');assert.ok(fs.existsSync(file),'credit limit parser missing');
 const m=new Module(file);m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,file);
 return m.exports.parseCreditLimit(value);
}
test('credit limits are converted exactly to milli-credits',()=>{assert.equal(parse('0.1'),100);assert.equal(parse('12.3'),12300);assert.equal(parse('100000'),100000000);});
test('invalid or excessive limits do not authorize spending',()=>{for(const input of ['', '-1','1.23','Infinity','NaN','0','100001','1e4','bad'])assert.equal(parse(input),null,input);});
function load(){
 const file=path.resolve(__dirname,'../src/features/agent/credit-limit.ts');
 const m=new Module(file);m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,file);
 return m.exports;
}
test('an empty limit is sendable only when the automatic limit and the balance cover the ceiling',()=>{
 const {creditLimitReady}=load();
 const base={estimated:true,typed:false,maximum:null,ceiling:3000,available:10000};
 assert.equal(creditLimitReady({...base,automatic:100000}),true);
 assert.equal(creditLimitReady({...base,automatic:null}),false,'automatic off: a typed limit is required');
 assert.equal(creditLimitReady({...base}),false,'older server without the field');
 assert.equal(creditLimitReady({...base,automatic:2000}),false,'ceiling above the automatic limit');
 assert.equal(creditLimitReady({...base,automatic:100000,available:2000}),false,'balance below the ceiling');
 assert.equal(creditLimitReady({...base,automatic:100000,estimated:false}),false,'no estimate yet');
});
test('something typed never falls back to the automatic limit, and a typed limit keeps its own checks',()=>{
 const {creditLimitReady}=load();
 const base={estimated:true,ceiling:3000,available:10000,automatic:100000};
 assert.equal(creditLimitReady({...base,typed:true,maximum:null}),false,'invalid typed value');
 assert.equal(creditLimitReady({...base,typed:true,maximum:2000}),false,'below the ceiling');
 assert.equal(creditLimitReady({...base,typed:true,maximum:20000}),false,'above the balance');
 assert.equal(creditLimitReady({...base,typed:true,maximum:5000}),true);
 assert.equal(creditLimitReady({...base,typed:true,maximum:5000,automatic:null}),true,'explicit limits work with automatic off');
});
