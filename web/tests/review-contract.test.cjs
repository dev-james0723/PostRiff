const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const test = require('node:test');
const ts = require('typescript');
const { z } = require('zod');
const file = path.join(__dirname, '../src/lib/analytics/review-contract.ts');
test('review runtime contract exists', () => assert.ok(fs.existsSync(file), 'A validated review contract is required'));
if (fs.existsSync(file)) {
  function load(source){const out={exports:{}};const localRequire=name=>name.startsWith('.')?load(path.resolve(path.dirname(source),name)+'.ts'):require(name);new Function('require','exports','module',ts.transpileModule(fs.readFileSync(source,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(localRequire,out.exports,out);return out.exports;}
  const t = load(file);
  const period = { start:'2026-10-01T00:00:00Z',end:'2026-10-04T00:00:00Z',timezone:'America/New_York' };
  test('UTC half-open dates and IANA timezone',()=>{
    assert.ok(t.publicationPeriodSchema.safeParse(period).success);
    assert.ok(t.publicationPeriodSchema.safeParse({...period,start:'2026-10-01T00:00:00Z',end:'2026-10-01T00:00:00.000001Z'}).success);
    for(const patch of [{end:period.start},{timezone:'bad/zone'},{start:'2026-10-01'}]) assert.equal(t.publicationPeriodSchema.safeParse({...period,...patch}).success,false);
  });
  test('true zero, unknown and invalid numbers are distinct',()=>{
    assert.ok(t.nativeValueSchema.safeParse(0).success);
    assert.ok(t.nativeValueSchema.safeParse(null).success);
    for(const v of [true,false,-1,NaN,Infinity,'0']) assert.equal(t.nativeValueSchema.safeParse(v).success,false);
  });
  test('input forbids provider claims and client lineage',()=>{
    const input={channelIds:['owned'],publicationPeriod:period,horizon:'24h'};
    assert.ok(t.reviewContextInputSchema.safeParse(input).success);
    for(const field of ['providers','trendLineage','contextDigest']) assert.equal(t.reviewContextInputSchema.safeParse({...input,[field]:[]}).success,false);
  });
  test('current access overrides a cached measured zero',()=>{
    assert.equal(t.reviewDisplayState({accessState:'revoked',valueState:'measured',value:0,freshnessState:'current',collectionState:'measured'}),'revoked');
    assert.equal(t.reviewDisplayState({accessState:'allowed',valueState:'measured',value:0,freshnessState:'current',collectionState:'measured'}),'measured_zero');
  });
  test('completed collection does not turn a missing or unsupported value into measured',()=>{
    for(const valueState of ['missing','invalid'])assert.equal(t.reviewDisplayState({accessState:'allowed',valueState,value:null,freshnessState:'current',collectionState:'measured'}),'unavailable');
    assert.equal(t.reviewDisplayState({accessState:'allowed',valueState:'unsupported',value:null,freshnessState:'current',collectionState:'measured'}),'unsupported');
  });
  test('relative baseline input resolves separately from the fixed report contract',()=>{
    const scope={channelIds:['owned'],relativeDateRule:{kind:'this_week',timezone:'America/New_York'},comparison:{kind:'previous_period',relativeToPublicationPeriod:true}};
    assert.ok(t.reviewContextInputSchema.safeParse(scope).success);
    assert.equal(t.comparisonSchema.safeParse(scope.comparison).success,false);
    assert.equal(t.reviewContextInputSchema.safeParse({...scope,comparison:{...scope.comparison,publicationPeriod:period}}).success,false);
  });
  test('generated schema matches canonical runtime',()=>{
    const defs=Object.fromEntries(Object.entries(t).filter(([,v])=>v instanceof z.ZodType).map(([k,v])=>[k,z.toJSONSchema(v,{io:'input'})]));
    const schema={$schema:'https://json-schema.org/draft/2020-12/schema',title:'Rafii review projection 1.0',$defs:defs};
    const destination=path.join(__dirname,'../../docs/design/rafii-insights-growth/review.schema.json');
    if(process.argv.includes('--write-schema')) fs.writeFileSync(destination,JSON.stringify(schema,null,2)+'\n');
    else assert.deepEqual(JSON.parse(fs.readFileSync(destination,'utf8')),schema);
  });
}
