const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),ts=require('typescript');
const web=path.resolve(__dirname,'..');
function load(rel){const mod={exports:{}};new Function('require','module','exports',ts.transpileModule(fs.readFileSync(path.join(web,rel),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(require,mod,mod.exports);return mod.exports;}
test('actual billing suggestions and walkthrough cannot advertise media or batch allowance to v2',()=>{
 const p=load('src/lib/site-agent/panel-logic.ts'),g=load('src/features/rafii-guide/guides.ts');
 assert.doesNotMatch(JSON.stringify(p.suggestionsFor('billing',false)),/writing batch|media credit/i);
 assert.doesNotMatch(JSON.stringify(g.guideFor('check_plan')),/writing batch|media credit|top up/i);
});
test('Models page information and actual help corpus do not claim legacy batches for a managed plan',()=>{
 const file=path.join(web,'src/features/account/models-view.tsx'),tree=ts.createSourceFile(file,fs.readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);let info;
 function visit(n){if(ts.isVariableDeclaration(n)&&n.name.getText(tree)==='infoContent')info=new Function('return '+n.initializer.getText(tree))();ts.forEachChild(n,visit);}visit(tree);
 assert.ok(info);assert.doesNotMatch(JSON.stringify(info),/writing batch|media credit/i);
 for(const f of ['billing.md','privacy-and-models.md'])assert.doesNotMatch(fs.readFileSync(path.join(web,'../src/postriff_phase2/site_agent/help',f),'utf8'),/writing batch|media credit/i);
 const manifest=JSON.parse(fs.readFileSync(path.join(web,'src/lib/site-agent/guide-manifest.json'),'utf8'));
 const guide=manifest.guides.find(g=>g.id==='check_plan');
 assert.doesNotMatch(JSON.stringify({title:guide.title,summary:guide.summary}),/media credit|writing batch/i);
 assert.ok(guide.keywords.includes('media credits'),'legacy search synonym remains compatible; keywords are retrieval metadata, not customer copy');
});

test('paid writer costCopy is compatible with both billing modes and never invents a per-batch charge',()=>{
 const file=path.join(web,'src/features/account/models/catalog.ts'),tree=ts.createSourceFile(file,fs.readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true);let fn;
 function visit(n){if(ts.isFunctionDeclaration(n)&&n.name?.text==='costCopy')fn=n;ts.forEachChild(n,visit);}visit(tree);assert.ok(fn);
 const code=ts.transpileModule(fn.getText(tree),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
 const cost=new Function('exports',code+';return costCopy("paid");')({});
 assert.equal(cost.badge,'Task allowance');assert.match(cost.line,/approved task allowance/);assert.doesNotMatch(JSON.stringify(cost),/writing batch|one.*run/i);
});

test('global attention never derives a legacy zero-batch warning for Free or Creator; legacy remains actionable',()=>{
 const file=path.join(web,'src/lib/attention.ts'),mod={exports:{}};
 const unsupported=new Proxy({},{get:()=>()=>assert.fail('unavailable channel/time inputs cannot fabricate attention')});
 const code=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
 new Function('require','module','exports',code)(name=>{assert.ok(['@/lib/channels/state','@/lib/time'].includes(name));return unsupported;},mod,mod.exports);
 const derive=mode=>mod.exports.deriveAttention({snapshot:{isError:false},channels:{isError:false},usage:{isError:false,data:{billingMode:mode,entitlement:{writingBatchesRemaining:0}}},now:1}).items;
 for(const mode of ['free_preview','managed_credits',undefined])assert.equal(derive(mode).find(i=>i.id==='writing-allowance'),undefined,mode);
 assert.equal(derive('legacy_allowances').find(i=>i.id==='writing-allowance').title,'Writing allowance used up');
});
