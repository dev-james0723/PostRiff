/** Local UI + real services + disposable data, with all external requests blocked. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const {randomUUID}=require('node:crypto');const {execFileSync}=require('node:child_process');
const base='http://127.0.0.1:3296',principal=randomUUID(),root=path.resolve(__dirname,'../..');
const python=process.env.POSTRIFF_TEST_PYTHON || 'python3';
const out=process.env.POSTRIFF_GROWTH_EVIDENCE_DIR || path.join(root,'docs/design/growth-phase2/evidence');fs.mkdirSync(out,{recursive:true});
const headers={'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',Authorization:'Bearer dev:'+principal,Origin:base};
async function api(method,url,body){const r=await fetch(base+url,{method,headers,...(body?{body:JSON.stringify(body)}:{})});assert.ok(r.ok,`${url}: ${r.status} ${await r.clone().text()}`);return r.json()}
(async()=>{
assert.equal((await api('GET','/api/auth/config')).execution,'dev-synthetic');
const {workspaceId:wid}=await api('POST','/api/auth/verify',{plan:'studio'});
execFileSync(python,['tests/phase2/growth_phase2_browser_fixture.py','55796',principal,wid],{cwd:root});
const tours=Object.fromEntries([...fs.readFileSync(path.join(root,'web/src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>[m[1],1]));
const browser=await chromium.launch({headless:true}),context=await browser.newContext({viewport:{width:1440,height:1100},reducedMotion:'reduce'});
await context.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base},{name:'postriff_theme',value:'rafii',url:base}]);
await context.addInitScript(({principal,wid,tours})=>{localStorage.setItem('postriff-dev-principal',principal);localStorage.setItem('postriff-workspace',wid);localStorage.setItem('postriff-onboarding',JSON.stringify({completed:{},dismissed:tours,nudged:{}}))},{principal,wid,tours});
const page=await context.newPage(),errors=[],checks=[];page.on('pageerror',e=>{errors.push(e.message);console.log('Page error:',e.message)});page.on('requestfailed',r=>console.log('Failed request:',r.url(),r.failure()?.errorText));page.on('console',m=>{if(m.type()==='error')console.log('Console:',m.text().slice(0,800))});
async function shot(name){await page.evaluate(()=>{window.scrollTo(0,0);let p=document.querySelector('.growth-studio');while(p){p.scrollTop=0;p=p.parentElement}});await page.screenshot({path:path.join(out,name+'.png'),fullPage:true})}
async function audit(name){
await page.locator('.growth-studio').evaluate(async e=>{await Promise.all(e.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{})))});
const overflow=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth,elements:[...document.querySelectorAll('.growth-studio *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,15).map(e=>({tag:e.tagName,class:e.className,width:e.getBoundingClientRect().width,scroll:e.scrollWidth}))}));
assert.ok(overflow.width<=overflow.viewport,name+' overflow '+JSON.stringify(overflow));
await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
const v=await page.evaluate(async()=> (await window.axe.run('.growth-studio',{resultTypes:['violations']})).violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})));
assert.deepEqual(v,[],name+' accessibility');}
try{
await page.goto(base+'/app/growth',{waitUntil:'domcontentloaded',timeout:120000});
await page.getByRole('button',{name:'1h',exact:true}).click();
await page.getByRole('heading',{name:'Post readings are not enabled.',exact:true}).waitFor();
assert.equal(await page.getByRole('button',{name:'Review this result',exact:true}).count(),0);
await page.getByRole('button',{name:'7d',exact:true}).click();
await page.getByRole('heading',{name:'Post readings are not enabled.',exact:true}).waitFor();
await page.getByRole('button',{name:'24h',exact:true}).click();
await page.getByRole('heading',{name:'The reading is in. Find the useful part.',exact:true}).waitFor();
checks.push('disabled collection is unavailable rather than pending; retained observed readings remain inspectable');
await page.getByText('AI permissions & daily allowances').click();
await page.getByRole('checkbox',{name:'Allow comment analysis'}).check();
await page.getByRole('checkbox',{name:'Allow growth AI models'}).check();
await page.getByRole('button',{name:'Allow growth AI',exact:true}).click();
await page.getByRole('checkbox',{name:'Use the allowed AI models to review these readings within my daily allowance.'}).check();
await page.getByRole('button',{name:'Review this result',exact:true}).click();
await page.getByText('A lesson for your Genome?').waitFor({timeout:60000});
await page.getByText('AI permissions & daily allowances').click();
await audit('desktop result');await shot('results-desktop');
await page.getByRole('radio').first().check();
await page.getByRole('checkbox',{name:'I reviewed this lesson. Save a new Genome version; limited evidence stays an observation.'}).check();
await page.getByRole('button',{name:'Save to my Genome'}).click();
await page.getByText('Saved as a new Genome version.',{exact:false}).waitFor();
let state=await api('GET',`/api/workspaces/${wid}`);assert.equal(state.state.brandHub.genome.statements.length,1);assert.equal(state.state.phase2.jobs.length,6);
checks.push('result review, native comparison, explicit Genome approval and no publishing');
await page.getByRole('tab',{name:'Your audience'}).click();
await page.getByRole('checkbox',{name:'Analyze these eligible comments with the allowed AI models within my daily allowance.'}).check();
await page.getByRole('button',{name:'Find audience insights'}).click();
await page.locator('.growth-cluster').first().waitFor({timeout:60000});assert.equal(await page.locator('.growth-cluster').count(),4);
const firstTitle=await page.locator('.growth-cluster h5').first().innerText();const cluster=page.locator('.growth-cluster').filter({has:page.getByRole('heading',{name:firstTitle,exact:true})});await cluster.locator('summary').click();
await cluster.getByRole('checkbox').check();await cluster.getByRole('button',{name:'Save this idea'}).click();await cluster.getByText('Saved to Ideas').waitFor();
await audit('desktop audience');await shot('audience-desktop');
state=await api('GET',`/api/workspaces/${wid}`);assert.equal(state.state.sources.filter(s=>s.audienceEvidence).length,1);assert.equal(state.state.phase2.jobs.length,6);
checks.push('Threads privacy abstention, classified evidence, saved idea and normal draft boundary');
await page.setViewportSize({width:390,height:844});await audit('mobile audience');await shot('audience-mobile');
await page.getByRole('tab',{name:'Your audience'}).focus();await page.keyboard.press('ArrowRight');await page.getByRole('tabpanel').getByText('Your history sets the context.').waitFor();
assert.equal(await page.getByRole('button',{name:'Prepare a calibration'}).isDisabled(),true);await audit('mobile patterns');await shot('patterns-mobile');
await page.setViewportSize({width:320,height:740});await audit('narrow patterns');
await page.getByRole('tab',{name:'Your results'}).click();await audit('narrow result');await shot('results-narrow');
await page.setViewportSize({width:1440,height:1100});
await page.evaluate(()=>document.documentElement.classList.add('dark'));await audit('dark result');await shot('results-dark');
checks.push('1440px, 390px, 320px, dark mode, reduced motion, keyboard tabs and axe serious/critical checks');
await page.evaluate(()=>document.documentElement.classList.remove('dark'));
await page.goto(base+'/app/workspace/brand',{waitUntil:'domcontentloaded'});await page.getByLabel('Creator Genome',{exact:true}).waitFor();await shot('genome-desktop');
await page.goto(base+'/app',{waitUntil:'domcontentloaded'});await page.locator('.growth-entry').waitFor();await shot('home-desktop');
checks.push('shared visual system and Growth Studio entry on Home and Genome');
execFileSync(python,['tests/phase2/growth_phase2_browser_fixture.py','55796',principal,wid,'empty'],{cwd:root});
await page.goto(base+'/app/growth',{waitUntil:'domcontentloaded'});
await page.getByRole('heading',{name:'Native post analytics are unavailable.',exact:true}).waitFor();
assert.equal(await page.getByRole('button',{name:'Review this result',exact:true}).count(),0);
assert.equal(await page.getByRole('link',{name:'Connect analytics'}).getAttribute('href'),'/app/channels');
await page.setViewportSize({width:390,height:844});await audit('mobile native analytics unavailable');await shot('native-analytics-unavailable-mobile');
await page.getByRole('link',{name:'Connect analytics'}).click();
await page.waitForURL(base+'/app/channels');
await page.getByRole('heading',{name:'Accounts',exact:true}).waitFor();
checks.push('missing native connection is explicit on mobile and the connection link opens the Accounts flow');
assert.deepEqual(errors,[]);
fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({status:'PASS',execution:'zero-network deterministic fixtures, disposable database',checks,realModelCalls:0,consoleErrors:errors},null,2));
console.log(JSON.stringify({status:'PASS',checks}));
}catch(e){await shot('failure');console.log((await page.locator('body').innerText()).slice(-6500));throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
