/* Real browser + real HTTP/services/PostgreSQL; explicitly synthetic native data. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {randomUUID}=require('node:crypto'),{execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),base=process.env.POSTRIFF_REVIEW_WEB_ORIGIN||'http://127.0.0.1:33404';
const out=process.env.POSTRIFF_REVIEW_EVIDENCE_DIR||path.join(root,'docs/design/rafii-insights-growth/evidence');fs.mkdirSync(out,{recursive:true});
const python=process.env.POSTRIFF_TEST_PYTHON||'python3',principal=randomUUID(),headers={'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',Authorization:'Bearer dev:'+principal,Origin:base};
async function api(method,url,body){const r=await fetch(base+url,{method,headers,...(body?{body:JSON.stringify(body)}:{})});assert.ok(r.ok,`${method} ${url}: ${r.status} ${await r.clone().text()}`);return r.json();}
async function seed(wid,mode='seed'){execFileSync(python,['tests/phase2/review_fixture.py','55404',principal,wid,mode],{cwd:root});}
(async()=>{
assert.equal((await api('GET','/api/auth/config')).execution,'dev-synthetic');
const {workspaceId:wid}=await api('POST','/api/auth/verify',{plan:'studio'});await seed(wid);
const tours=Object.fromEntries([...fs.readFileSync(path.join(root,'web/src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>[m[1],1]));
const browser=await chromium.launch({headless:true,channel:'chrome'});const context=await browser.newContext({viewport:{width:1440,height:1100},reducedMotion:'reduce'});
await context.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base},{name:'postriff_theme',value:'rafii',url:base}]);
await context.addInitScript(({principal,wid,tours})=>{localStorage.setItem('postriff-dev-principal',principal);localStorage.setItem('postriff-workspace',wid);localStorage.setItem('postriff-onboarding',JSON.stringify({completed:{},dismissed:tours,nudged:{}}));},{principal,wid,tours});
const page=await context.newPage(),errors=[],requests=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/api/'))requests.push({method:r.method(),url:new URL(r.url()).pathname});});
const panel=page.getByRole('region',{name:'Evidence review',exact:true});
async function ready(){await panel.getByText('12 of 12 publications have qualified readings.',{exact:false}).waitFor({timeout:120000});}
async function shot(name){await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});}
async function audit(name){
  const overflow=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth}));assert.ok(overflow.width<=overflow.viewport,name+' '+JSON.stringify(overflow));
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const violations=await panel.evaluate(async e=>(await window.axe.run(e,{resultTypes:['violations']})).violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})));
  assert.deepEqual(violations,[],name+' accessibility');
}
try{
await page.goto(base+'/app/analytics',{waitUntil:'domcontentloaded',timeout:120000});await ready();
const crossPage=panel.getByRole('link',{name:'Open this scope in Growth Studio',exact:true});
const sharedInput=JSON.parse(new URL(await crossPage.getAttribute('href'),base).searchParams.get('reviewScope'));
const sharedProjection=await api('GET',`/api/workspaces/${wid}/coworker/review?scope=${encodeURIComponent(JSON.stringify(sharedInput))}`);
await crossPage.click();await ready();
assert.deepEqual(JSON.parse(new URL(page.url()).searchParams.get('reviewScope')),sharedInput);
await panel.getByRole('link',{name:'Open this scope in Analytics',exact:true}).click();await ready();
assert.equal((await api('GET',`/api/workspaces/${wid}/coworker/review?scope=${encodeURIComponent(JSON.stringify(sharedInput))}`)).contextDigest,sharedProjection.contextDigest);
checks.push('Analytics to Growth Studio to Analytics preserves exact resolved dates, cutoff, comparison and context digest');
await panel.locator('summary').filter({hasText:'Metric sources, missing values and exact reading times'}).click();
await panel.getByText('likes: 0',{exact:false}).waitFor();assert.ok(!(await panel.innerText()).includes('SYNTHETIC-SECRET'));
await panel.locator('summary').filter({hasText:'Saved Views and classifications'}).click();
await panel.getByLabel('View name',{exact:true}).fill('Weekly teaching');await panel.getByRole('button',{name:'Save current view',exact:true}).click();
await panel.getByText('Saved View saved. Relative dates resolve when reopened.',{exact:true}).waitFor();
await panel.getByRole('button',{name:'Update Saved View',exact:true}).waitFor();
await panel.getByLabel('Classification ID',{exact:true}).fill('practice-series');await panel.getByLabel('Classification label',{exact:true}).fill('Practice series');
await panel.getByRole('button',{name:'Confirm classification',exact:true}).click();
await panel.getByText('Classification version 1 saved for one publication.',{exact:false}).waitFor();
await panel.getByLabel('Classification filter',{exact:true}).selectOption('practice-series');
await panel.getByText('1 of 1 publications have qualified readings.',{exact:false}).waitFor();assert.equal(await panel.getByText('Too few comparable publications for a takeaway.',{exact:false}).count(),1);
await panel.getByLabel('Classification filter',{exact:true}).selectOption('');await ready();
await panel.getByRole('button',{name:'Propose this controlled test',exact:true}).click();
await panel.getByText('Existing Growth Loop experiment proposed. Owner acceptance and preparation remain separate.',{exact:true}).waitFor();await ready();
await audit('desktop');await shot('review-desktop');
checks.push('real HTTP read projection, measured zero / missing sources, Saved View save, versioned classification and scoped low sample; explicit bounded test creates existing Growth Loop proposal without publication');
for(const width of [390,430]){await page.setViewportSize({width,height:900});await audit(String(width));await shot('review-'+width);}
await panel.getByLabel('Post age',{exact:true}).focus();await page.keyboard.press('Tab');
assert.ok(await panel.getByLabel('Review timezone',{exact:true}).evaluate(e=>e===document.activeElement),'Keyboard focus reaches timezone');
await page.keyboard.press('ControlOrMeta+A');await page.keyboard.type('America/Indiana/Indianapolis');await ready();
await panel.getByLabel('Post age',{exact:true}).selectOption('1h');
await panel.getByText('No comparable native readings in this scope.',{exact:false}).waitFor();
await panel.getByLabel('Post age',{exact:true}).selectOption('24h');await ready();
checks.push('1440 / 390 / 430px, no page overflow, axe serious/critical, keyboard scope operation');
await panel.locator('summary').filter({hasText:'Fixed weekly / monthly report'}).click();
const note='繁體中文週回顧，支持證據與反證。'.repeat(170)+'最後一行：來源與註記完整保留。';
await panel.getByLabel('Human notes',{exact:true}).fill(note);
await panel.getByRole('button',{name:'Save fixed report',exact:true}).click();
await panel.getByText('Fixed report version 1 saved.',{exact:true}).waitFor();
for(const [name,extension] of [['Download Markdown','md'],['Download CSV','csv']]){
  const downloadPromise=page.waitForEvent('download');await panel.getByRole('button',{name,exact:true}).click();const download=await downloadPromise;await download.saveAs(path.join(out,'report.'+extension));
}
const saved=await api('GET',`/api/workspaces/${wid}/coworker/review/views`),last=saved.snapshots.at(-1);
const snapshot=await api('GET',`/api/workspaces/${wid}/coworker/review/snapshots/${last.snapshotId}?version=${last.version}`);
assert.equal(snapshot.sourceSha,process.env.POSTRIFF_SOURCE_SHA);
const pdf=await api('GET',`/api/workspaces/${wid}/coworker/review/snapshots/${last.snapshotId}/export?version=1&format=pdf`);
assert.equal(pdf.rendering,'browser_print_pdf');assert.equal(pdf.payloadDigest,snapshot.payloadDigest);
const printPage=await context.newPage();await printPage.setContent(pdf.content);await printPage.emulateMedia({media:'print'});
await printPage.pdf({path:path.join(out,'report.pdf'),format:'A4',printBackground:true,preferCSSPageSize:true});
await printPage.screenshot({path:path.join(out,'report-print.png'),fullPage:true});await printPage.close();
for(const f of ['report.md','report.csv']){const text=fs.readFileSync(path.join(out,f),'utf8');assert.ok(text.includes(snapshot.snapshotId)&&text.includes(snapshot.payloadDigest)&&text.includes('最後一行：來源與註記完整保留。'));}
const extracted=execFileSync('/opt/homebrew/bin/pdftotext',[path.join(out,'report.pdf'),'-'],{encoding:'utf8'});
for(const text of [snapshot.snapshotId,'繁體中文週回顧','最後一行：來源與註記完整保留。'])assert.ok(extracted.replace(/\s/g,'').includes(text),'PDF text '+text);
fs.writeFileSync(path.join(out,'pdf-text.txt'),extracted);
assert.ok(extracted.split('\f').length>=3,'Long note should span multiple readable pages');
await panel.getByLabel('Human notes',{exact:true}).fill('New note');await panel.getByRole('button',{name:'Save new report version',exact:true}).click();
await panel.getByText('Fixed report version 2 saved.',{exact:true}).waitFor();
assert.deepEqual((await api('GET',`/api/workspaces/${wid}/coworker/review/snapshots/${last.snapshotId}?version=1`)).humanNotes,[note]);
checks.push('UI fixed report, notes create v2, MD / CSV same payload, actual multi-page CJK PDF render and extracted final note');
// Slow scope response: old values and all report/reuse actions disappear at once.
let release;const held=new Promise(resolve=>release=resolve);
await page.route(`**/coworker/review?*`,async route=>{if(route.request().url().includes('7d'))await held;await route.continue();});
await panel.getByLabel('Post age',{exact:true}).selectOption('7d');await panel.getByText('Loading the current scope…',{exact:true}).waitFor();
assert.equal(await panel.getByRole('button',{name:'Download CSV',exact:true}).count(),0);assert.equal(await panel.getByText('likes: 0',{exact:false}).count(),0);
release();await panel.getByText('No comparable native readings in this scope.',{exact:false}).waitFor();await page.unroute(`**/coworker/review?*`);
await panel.getByLabel('Post age',{exact:true}).selectOption('24h');await ready();
await page.route(`**/coworker/review?*`,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Test read unavailable'})}));
await panel.getByLabel('Post age',{exact:true}).selectOption('1h');await panel.getByRole('alert').waitFor();
assert.equal(await panel.getByRole('button',{name:'Download CSV',exact:true}).count(),0);await shot('review-error');await page.unroute(`**/coworker/review?*`);
await panel.getByLabel('Post age',{exact:true}).selectOption('24h');await ready();
checks.push('delayed new scope and read error immediately remove old values/actions/hidden report DOM');
await seed(wid,'stale');await page.reload();await ready();
await panel.locator('summary').filter({hasText:'Metric sources, missing values and exact reading times'}).click();
await panel.getByText('Earlier reading; a later attempt failed',{exact:false}).waitFor();await shot('review-stale');
await seed(wid,'partial');await page.reload();await panel.getByText('11 of 12 publications have qualified readings.',{exact:false}).waitFor();await shot('review-partial');
checks.push('real PG later unavailable attempt preserves old value with stale label; partial coverage retains missing values and per-metric sample counts');
await seed(wid,'revoked');await page.goto(base+'/app/analytics?reviewScope='+encodeURIComponent(JSON.stringify(saved.views[0].filterDefinition)));await panel.getByText('No comparable native readings in this scope.',{exact:false}).waitFor();
assert.equal(await panel.getByText('likes: 0',{exact:false}).count(),0);assert.ok(!(await panel.innerText()).includes('A bounded question about practice?'));await shot('review-revoked');
await seed(wid,'empty');await page.goto(base+'/app/analytics');await panel.getByText('No connected account.',{exact:false}).waitFor();await shot('review-empty');
checks.push('real backend revocation removes values and content; empty account state remains actionable');
const paid=requests.filter(r=>r.method==='POST'&&/postmortem|calibration|generate|publish|quote|model|history-import/.test(r.url));assert.deepEqual(paid,[]);
assert.deepEqual(errors,[]);const evidence={status:'PASS',execution:'real browser HTTP + disposable PG, synthetic native data; error/latency injected only for transport states',sourceSha:process.env.POSTRIFF_SOURCE_SHA,checks,realProviderCalls:0,realModelCalls:0,nativeAcceptance:false,pdf:{pages:extracted.split('\f').length-1,cjkExtracted:true},consoleErrors:errors};
fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify(evidence,null,2)+'\n');console.log(JSON.stringify(evidence));
}catch(error){await shot('review-failure');console.log((await panel.innerText().catch(()=>page.locator('body').innerText())).slice(-4200));throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
