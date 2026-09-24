const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
const filename=path.resolve(__dirname,'../src/lib/telemetry.ts');
const loaded=new Module(filename);
loaded._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,filename);
const {scrubTelemetry}=loaded.exports;
test('error export removes content, identities, credentials, breadcrumbs and URL queries',()=>{
 const event={type:undefined,event_id:'diagnostic-id',level:'error',release:'release-id',message:'PRIVATE',user:{email:'PRIVATE'},request:{headers:{authorization:'PRIVATE'},data:'PRIVATE'},breadcrumbs:[{message:'PRIVATE'}],extra:{draft:'PRIVATE'},contexts:{session:'PRIVATE'},exception:{values:[{type:'TypeError',value:'PRIVATE',stacktrace:{frames:[{filename:'https://app.example/_next/static/app.js?token=PRIVATE#PRIVATE',lineno:12,colno:3,vars:{draft:'PRIVATE'},context_line:'PRIVATE'}]}}]}};
 const output=scrubTelemetry(event);
 assert.equal(JSON.stringify(output).includes('PRIVATE'),false);
 assert.equal(output.event_id,event.event_id);assert.equal(output.exception.values[0].stacktrace.frames[0].lineno,12);
 assert.equal(event.exception.values[0].value,'PRIVATE');
});
test('stack metadata cannot carry credentials, user paths or free-form exception types',()=>{
 const output=scrubTelemetry({type:undefined,exception:{values:[{type:'PRIVATE',stacktrace:{frames:[{filename:'https://PRIVATE@app.example/_next/static/app.js',function:'PRIVATE'},{filename:'https://app.example/api/private/PRIVATE'},{filename:'/Users/PRIVATE/work/component.tsx'}]}}]}});
 assert.equal(JSON.stringify(output).includes('PRIVATE'),false);
 assert.equal(output.exception.values[0].stacktrace.frames[0].filename,'/_next/static/app.js');
});
