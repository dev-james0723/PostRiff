const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
function parse(value){
 const file=path.resolve(__dirname,'../src/features/agent/credit-limit.ts');assert.ok(fs.existsSync(file),'credit limit parser missing');
 const m=new Module(file);m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,file);
 return m.exports.parseCreditLimit(value);
}
test('credit limits are converted exactly to milli-credits',()=>{assert.equal(parse('0.1'),100);assert.equal(parse('12.3'),12300);assert.equal(parse('100000'),100000000);});
test('invalid or excessive limits do not authorize spending',()=>{for(const input of ['', '-1','1.23','Infinity','NaN','0','100001','1e4','bad'])assert.equal(parse(input),null,input);});
