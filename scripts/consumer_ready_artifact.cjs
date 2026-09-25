/** Build an actual Python function archive locally; no Vercel project, credentials or deployment. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),out=path.join(root,'docs/consumer-ready/evidence');
const modules=process.env.VERCEL_BUILDER_MODULES || path.join(root,'.codex/consumer-ready/vercel/node_modules');
(async()=>{
 const builderVersion=require(path.join(modules,'@vercel/python/package.json')).version;
 const cliVersion=require(path.join(modules,'vercel/package.json')).version;
 assert.equal(cliVersion,'59.23.2');assert.equal(builderVersion,'14.2.0');
 const utils=require(path.join(modules,'@vercel/build-utils'));
 const ignored=await require(path.join(modules,'@vercel/build-utils/dist/get-ignore-filter.js')).default(root);
 const uploaded=[];
 function walk(dir,rel='') {for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
  const name=rel+entry.name;if(ignored(name+(entry.isDirectory()?'/':'')))continue;
  if(entry.isSymbolicLink())throw new Error('Unreviewed symlink in source upload: '+name);
  if(entry.isDirectory())walk(path.join(dir,entry.name),name+'/');else uploaded.push(name);
 }}
 walk(root);
 const forbidden=/(^|\/)(\.env[^/]*|broker\.key|vendor|\.codex|\.token-pilot|\.claude|\.agents|\.git|tests|node_modules|\.next[^/]*|.*-broker-.*)(\/|$)/;
 assert.deepEqual(uploaded.filter(n=>forbidden.test(n)||n.startsWith('docs/')),[]);
 for(const name of ['api/index.py','src/postriff_phase2/locale_catalogue.json','skills/postriff-voice/SKILL.md']) {
  if(name.includes('postriff-voice'))assert(uploaded.some(n=>n.startsWith('skills/postriff-')&&n.endsWith('/SKILL.md')));
  else assert(uploaded.includes(name),name);
 }
 // Fresh directory every run, filtered inputs only; neither environment files nor broker state are copied.
 const work=fs.mkdtempSync(path.join(root,'.codex/consumer-ready/python-artifact-'));
 const files=Object.fromEntries(uploaded.map(name=>[name,new utils.FileFsRef({fsPath:path.join(root,name)})]));
 fs.writeFileSync(path.join(out,'source-upload-manifest.json'),JSON.stringify({execution:'local source selection with Vercel 59.23.2 ignore implementation; not uploaded',files:uploaded},null,2));
 const config=JSON.parse(fs.readFileSync(path.join(root,'vercel.json'),'utf8')).services.postriff_api;
 const keep=new Set(['PATH','HOME','TMPDIR','LANG','LC_ALL']);for(const key of Object.keys(process.env))if(!keep.has(key))delete process.env[key];
 process.env.VERCEL_TELEMETRY_DISABLED='1';
 const result=await require(path.join(modules,'@vercel/python')).build({workPath:work,repoRootPath:work,files,entrypoint:'api/index.py',meta:{isDev:false},config:{functions:config.functions}});
 assert.equal(result.resultVersion,3);
 const artifact=result.result.output;
 assert.equal(typeof artifact.createZip,'function');
 const names=Object.keys(artifact.files);
 assert(names.includes('src/postriff_phase2/locale_catalogue.json'));
 assert(names.some(n=>n.startsWith('skills/postriff-')&&n.endsWith('/SKILL.md')));
 // Third-party packages the builder vendors into _vendor/ may ship their own test modules (jsonschema, referencing, certifi):
 // those are upstream code, not this repository's tests. Every other private path stays forbidden everywhere, _vendor/ included.
 const forbiddenVendored=/(^|\/)(\.env[^/]*|broker\.key|\.codex|\.token-pilot|\.claude|\.agents|\.git|node_modules|\.next[^/]*|.*-broker-.*)(\/|$)/;
 assert.deepEqual(names.filter(n=>n.startsWith('_vendor/')?forbiddenVendored.test(n):forbidden.test(n)),[]);
 const zip=await artifact.createZip(),filename=path.join(work,'function.zip');fs.writeFileSync(filename,zip);
 const record={status:'PASS',execution:'actual local Vercel Python builder output; not deployed or invoked on Vercel',cliVersion,builderVersion,runtime:artifact.runtime,architecture:artifact.architecture,bytes:zip.length,sha256:crypto.createHash('sha256').update(zip).digest('hex'),archive:path.relative(root,filename),files:names.sort(),routes:JSON.parse(fs.readFileSync(path.join(root,'vercel.json'),'utf8')).rewrites};
 fs.writeFileSync(path.join(out,'python-artifact.json'),JSON.stringify(record,null,2));
 console.log(JSON.stringify({...record,files:names.length}));
})().catch(error=>{console.error(error);process.exitCode=1});
