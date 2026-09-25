/** Real local Next pages; synthetic API only, isolated browser, external requests blocked. */
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
const require=createRequire(import.meta.url);
const {chromium}=require('/Users/ouxianxing/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fixture=JSON.parse(readFileSync(new URL('./fixtures/wp04a-workspace.json',import.meta.url),'utf8'));
const base=process.env.WP04A_WEB_URL || 'http://127.0.0.1:4439';
assert.equal(new URL(base).hostname,'127.0.0.1');
const out=new URL('../../docs/postriff-research-20260918/evidence/wp04a/browser/',import.meta.url);mkdirSync(out,{recursive:true});
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
const checks=[];
try {
 for(const scenario of ['ready','memory-empty','memory-loading','memory-error','snapshot-error']) {
  const context=await browser.newContext({viewport:{width:1024,height:900},reducedMotion:'reduce'});
  await context.addCookies([{name:'postriff_dev',value:'1',url:base}]);
  await context.addInitScript(()=>{localStorage.setItem('postriff-dev-principal','00000000-0000-0000-0000-000000000001');localStorage.setItem('postriff-onboarding:00000000-0000-0000-0000-000000000001',JSON.stringify({completed:{},dismissed:{welcome:1},nudged:{'brand-tips':1,'queue-tips':1}}));});
  const page=await context.newPage();page.setDefaultTimeout(15000);page.setDefaultNavigationTimeout(30000);const errors=[],unexpected=[];
  page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});
  let releaseMemory;
  const memoryGate=new Promise(resolve=>{releaseMemory=resolve;});
  await context.route('**/*',async route=>{
   const u=new URL(route.request().url());
   if(u.origin!==base) return route.abort();
   if(!u.pathname.startsWith('/api/')) return route.continue();
   const send=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
   const wid=fixture.snapshot.state.workspace.id; const path=u.pathname;console.log('API '+path);
   if(route.request().method()!=='GET') {unexpected.push(route.request().method()+' '+path);return send({error:'Mutations forbidden in smoke'},403);}
   if(path==='/api/catalog') return send({authMode:'dev',execution:'dev-synthetic',phase2:true,templates:[],routes:[],profileMetadata:{}});
   if(path==='/api/workspaces') return send({workspaces:[{workspaceId:wid,membership:fixture.snapshot.membership,name:'WP04A synthetic workspace',createdAt:1800000000,plan:'studio',trialPlan:'studio',owner:null,memberCounts:{owner:1,admin:0,editor:0,approver:0,viewer:0}}]});
   if(path==='/api/me') return send({userId:'00000000-0000-0000-0000-000000000001',displayName:'WP04A fixture',sessionId:null,mfa:{available:false,enforced:false,enforcedAt:null,aal:null},preferences:{timeZone:'UTC',locale:'en',alertNewDevice:false}});
   if(path===`/api/workspaces/${wid}`) return scenario==='snapshot-error'?send({error:'Synthetic snapshot unavailable'},503):send(fixture.snapshot);
   if(path.endsWith('/usage')) return send({subscription:{plan:'studio',status:'active'},trial:{expiresAt:2000000000},balances:[]});
   if(path.endsWith('/channels')) return send({channels:[],providers:[]});
   if(path.endsWith('/memory')) {
    if(scenario==='memory-loading') await memoryGate;
    if(scenario==='memory-error') return send({error:'Synthetic memory unavailable'},503);
    const memory=structuredClone(fixture.memory);
    memory.learning.items=scenario==='memory-empty'?[]:[{id:'active',status:'active'},{id:'retired',status:'retired'}];
    return send(memory);
   }
   unexpected.push(path);return send({error:'Unhandled synthetic route'},404);
  });
  await page.goto(base+'/app/workspace/brand',{waitUntil:'domcontentloaded'});
  console.log(scenario+' loaded '+await page.title());
  writeFileSync(new URL(scenario+'-body.txt',out),await page.locator('body').innerText());
  try {await page.getByRole('heading',{name:/^Brand & voice/}).first().waitFor({timeout:30000});} catch(e) {console.log(await page.locator('body').innerText());throw e;}
  if(scenario==='snapshot-error') {
   await page.getByText('Couldn’t load this workspace',{exact:true}).waitFor({timeout:30000});
   await page.getByRole('button',{name:'Try again'}).waitFor();
  } else {
   const strip=page.locator('section[aria-label="Voice status"]');
   await strip.waitFor({timeout:30000});
   const count=strip.getByText('Learned preferences',{exact:true}).locator('..');
   if(scenario==='memory-loading') {await count.getByText('Loading',{exact:true}).waitFor();releaseMemory();await count.getByText('1',{exact:true}).first().waitFor();}
   else if(scenario==='memory-error') await count.getByText('Unavailable',{exact:true}).waitFor({timeout:30000});
   else await count.getByText(scenario==='memory-empty'?'0':'1',{exact:true}).first().waitFor();
  }
  await page.screenshot({path:new URL(scenario+'.png',out).pathname,fullPage:true});
  if(scenario==='ready') {
   await page.getByRole('tab',{name:'Identity',exact:true}).click();
   await page.keyboard.press('Tab');
   assert.ok(await page.locator(':focus').count());
   await page.setViewportSize({width:390,height:900});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.screenshot({path:new URL('brand-390.png',out).pathname,fullPage:true});
   for(const width of [390,1024]) {
    await page.setViewportSize({width,height:900});
    await page.goto(base+'/app/queue?job=fixture-held');
    const heldDialog=page.getByRole('dialog');
    await heldDialog.getByText(/^needs action$/i).first().waitFor({timeout:30000});
    const heldNote=heldDialog.getByText('Source approval changed. Review the current draft.',{exact:false}).last();
    await heldNote.scrollIntoViewIfNeeded();
    await heldDialog.getByRole('button',{name:'Prepare again',exact:true}).waitFor();
    await page.screenshot({path:new URL(`held-${width}.png`,out).pathname,fullPage:true});
    await page.goto(base+'/app/queue?job=fixture-uncertain');
    const uncertainDialog=page.getByRole('dialog');
    await uncertainDialog.getByText(/^result not confirmed$/i).first().waitFor({timeout:30000});
    const uncertainNote=uncertainDialog.getByText('Provider result unknown. Check the platform before another attempt.',{exact:false}).last();
    await uncertainNote.waitFor();
    assert.equal(await page.getByRole('link',{name:'Open verified post'}).count(),0);
    assert.equal(await page.getByRole('button',{name:'Prepare again',exact:true}).count(),0);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:new URL(`uncertain-${width}.png`,out).pathname,fullPage:true});
    await uncertainNote.scrollIntoViewIfNeeded();
    const box=await uncertainNote.boundingBox();assert.ok(box && box.y>=0 && box.y+box.height<=900,'uncertain explanation must be in the viewport');
    await page.screenshot({path:new URL(`uncertain-explanation-${width}.png`,out).pathname,fullPage:true});
   }
  }
  assert.deepEqual(errors,[],scenario+' browser exceptions');assert.deepEqual(unexpected,[],scenario+' unhandled API requests');
  checks.push({scenario,status:'pass'});console.log(JSON.stringify(checks.at(-1)));await context.close();
 }
} finally {await browser.close();writeFileSync(new URL('checks.json',out),JSON.stringify(checks,null,2));}
