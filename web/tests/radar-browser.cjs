/** Actual local UI/services/PG with deterministic providers. No external requests. */
const {chromium}=require('playwright');const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const {randomUUID}=require('node:crypto');
const base=process.env.RADAR_TEST_ORIGIN||'http://127.0.0.1:3298',principal=randomUUID(),root=path.resolve(__dirname,'../..');
const out=path.join(root,'docs/design/growth-phase3/evidence');fs.mkdirSync(out,{recursive:true});
const headers={'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',Authorization:'Bearer dev:'+principal,Origin:base};
async function api(method,url,body){const r=await fetch(base+url,{method,headers,...(body?{body:JSON.stringify(body)}:{})});assert.ok(r.ok,`${url}: ${r.status} ${await r.clone().text()}`);return r.json()}
(async()=>{
for(let i=0;i<15;i++){try{assert.equal((await api('GET','/api/auth/config')).execution,'dev-synthetic');break;}catch(e){if(i===14)throw e;await new Promise(r=>setTimeout(r,1000));}}
const {workspaceId:wid}=await api('POST','/api/auth/verify',{plan:'studio'});
const tours=Object.fromEntries([...fs.readFileSync(path.join(root,'web/src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>[m[1],1]));
const browser=await chromium.launch({headless:true}),context=await browser.newContext({viewport:{width:1440,height:1050},reducedMotion:'reduce'});
await context.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base},{name:'postriff_theme',value:'rafii',url:base}]);
await context.addInitScript(({principal,wid,tours})=>{localStorage.setItem('postriff-dev-principal',principal);localStorage.setItem('postriff-workspace',wid);localStorage.setItem('postriff-onboarding',JSON.stringify({completed:{},dismissed:tours,nudged:{}}))},{principal,wid,tours});
const page=await context.newPage(),errors=[],checks=[];page.setDefaultTimeout(60000);page.on('pageerror',e=>errors.push(e.message));
async function shot(name){await page.evaluate(()=>{let p=document.querySelector('.radar-page');while(p){p.scrollTop=0;p=p.parentElement}});await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});}
async function audit(name){
await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
const results=await page.evaluate(async()=>({overflow:document.documentElement.scrollWidth>innerWidth,violations:(await window.axe.run('.radar-page',{resultTypes:['violations']})).violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))}));
assert.equal(results.overflow,false,name+' overflow');assert.deepEqual(results.violations,[],name+' accessibility');}
try{
await page.goto(base+'/app/radar',{waitUntil:'domcontentloaded',timeout:120000});await page.locator('.radar-hero h1').waitFor();
await page.locator('.radar-permissions > summary').click();
await page.getByRole('checkbox',{name:'Allow growth AI models'}).check();await page.getByRole('button',{name:'Allow growth AI',exact:true}).click();await page.getByRole('button',{name:'Revoke growth AI permission'}).waitFor();
for(const name of ['Bluesky','News · GDELT','YouTube charts'])await page.getByRole('checkbox',{name,exact:true}).check();
await page.getByRole('checkbox',{name:'Allow Radar AI'}).check();await page.getByRole('button',{name:'Save Radar permissions'}).click();
await page.getByRole('textbox',{name:'What is your audience thinking about?'}).fill('piano practice');await page.getByRole('button',{name:'Review scan',exact:true}).click();
await page.getByRole('button',{name:'Confirm & scan'}).waitFor();let scans=await api('GET',`/api/workspaces/${wid}/growth/radar/scans`);assert.equal(scans.scans[0].status,'quoted');assert.equal(scans.scans[0].steps.length,0);
await page.getByRole('button',{name:'Confirm & scan'}).click();await page.locator('.radar-card').first().waitFor({timeout:90000});
assert.ok(await page.locator('.radar-card').count()>=3);const first=page.locator('.radar-card').first();await first.locator('summary').click();assert.ok(await first.locator('.radar-evidence a').count()>0);
await first.getByRole('checkbox',{name:'I reviewed the references'}).check();await first.getByRole('button',{name:'Save this idea'}).click();await first.getByRole('link',{name:'Saved to Ideas'}).waitFor();
let state=await api('GET',`/api/workspaces/${wid}`);assert.equal(state.state.sources.filter(s=>s.radarEvidence).length,1);assert.equal(state.state.phase2.jobs.length,0);
checks.push('owner permissions, source selection, quote before execution, bounded scan, inspectable evidence and saved idea without publishing');
await audit('desktop');await shot('radar-desktop');
await page.getByRole('button',{name:'For you',exact:true}).click();await page.getByText('Your fit will get clearer.').waitFor();checks.push('For You empty state without supported Genome');await page.getByRole('button',{name:'All signals',exact:true}).click();
await page.setViewportSize({width:390,height:844});const mobileCard=page.locator('.radar-card').nth(1);await mobileCard.getByRole('checkbox',{name:'I reviewed the references'}).check();await mobileCard.getByRole('button',{name:'Save this idea'}).click();await mobileCard.getByRole('link',{name:'Saved to Ideas'}).waitFor();checks.push('mobile reviewed idea action');await audit('mobile390');await shot('radar-mobile');await page.setViewportSize({width:320,height:740});await audit('mobile320');
await page.setViewportSize({width:1440,height:1050});await page.evaluate(()=>document.documentElement.classList.add('dark'));await audit('dark');await shot('radar-dark');await page.evaluate(()=>document.documentElement.classList.remove('dark'));
checks.push('1440/390/320 responsive, dark theme, reduced motion and no serious/critical axe violations');
await page.getByRole('button',{name:'Deep',exact:true}).click();await page.getByRole('button',{name:'Review scan',exact:true}).click();await page.getByRole('button',{name:'Confirm & scan'}).click();
await page.getByText(/completed · deep scan/).waitFor({timeout:90000});scans=await api('GET',`/api/workspaces/${wid}/growth/radar/scans`);assert.equal(scans.scans[0].mode,'deep');assert.equal(scans.scans[0].status,'completed');
await page.reload();await page.locator('.radar-card').first().waitFor();assert.equal((await api('GET',`/api/workspaces/${wid}/growth/radar/scans`)).scans.length,2);checks.push('Deep scan and persisted reload');
await page.goto(base+'/app',{waitUntil:'domcontentloaded'});await page.locator('.radar-home').waitFor();await page.locator('.radar-home').click();await page.locator('.radar-card').first().waitFor();checks.push('Home discovery and return to durable results');
assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify({status:'PASS',execution:'local real service + disposable PostgreSQL; synthetic identity, sources and AI',checks,realProviderCalls:0},null,2));console.log(JSON.stringify({status:'PASS',checks}));
}catch(e){console.error('Original failure:',e);try{await page.screenshot({path:path.join(out,'failure.png'),fullPage:true,timeout:5000});console.error((await page.locator('body').innerText({timeout:5000})).slice(-4000));}catch{}throw e;}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
