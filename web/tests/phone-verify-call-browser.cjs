/** Actual Next.js page + synthetic challenge API. Local only; no real passkey/provider request. */
const {chromium,webkit}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {randomUUID}=require('node:crypto');
const base=process.env.RAFII_WEB_URL||'http://localhost:3395';
assert.ok(['localhost','127.0.0.1'].includes(new URL(base).hostname));
const principal=randomUUID(),challenge=randomUUID();
const headers={Authorization:`Bearer dev:${principal}`,'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha'};
(async()=>{
 const r=await fetch(base+'/api/auth/verify',{method:'POST',headers,body:JSON.stringify({plan:'studio'})});assert.ok(r.ok,await r.clone().text());const workspace=(await r.json()).workspaceId;
 const tourIds=[...fs.readFileSync(path.join(__dirname,'../src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>m[1]);
 const evidence=path.join(__dirname,'../../docs/design/rafii-live-agent/caller-identity-2026-09-28/browser');fs.mkdirSync(evidence,{recursive:true});
 for(const [name,engine] of Object.entries({chromium,webkit})){
  const browser=await engine.launch({headless:true});
  try{
   for(const width of [1280,390,320]){
    const ctx=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
    await ctx.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base}]);
    await ctx.addInitScript(({principal,tourIds})=>{localStorage.setItem('postriff-dev-principal',principal);localStorage.setItem('postriff-onboarding',JSON.stringify({completed:{},dismissed:Object.fromEntries(tourIds.map(id=>[id,1])),nudged:{}}));},{principal,tourIds});
    let state='pending',posts=[];
    await ctx.route('**/api/phone/verify-call/**',async route=>{
     const req=route.request();if(req.method()==='POST'){const action=new URL(req.url()).pathname.split('/').at(-1);posts.push(action);state=action==='deny'?'denied':'fallback';}
     await route.fulfill({status:200,contentType:'application/json',headers:{'Cache-Control':'no-store'},body:JSON.stringify({state,startedAt:Date.now()/1000,expiresAt:Date.now()/1000+90,workspaceId:workspace,spending:{usesCredits:false,ceilingMilliCredits:100,availableMilliCredits:10000}})});
    });
    const page=await ctx.newPage();await page.goto(base+'/app/phone/verify-call?challenge='+challenge,{waitUntil:'domcontentloaded',timeout:120000});
    await page.getByRole('button',{name:'Verify this agent call with Face ID / Touch ID',exact:true}).waitFor({timeout:90000});
    assert.deepEqual(posts,[],'Opening notification never approves/dials');
    assert.ok(await page.getByRole('button',{name:'Verify this agent call with Face ID / Touch ID',exact:true}).isDisabled(),'Synthetic dev identity cannot invoke production passkey');
    await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
    const axe=await page.evaluate(async()=>window.axe.run(document.querySelector('main[aria-labelledby="verify-call-title"]'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}}));
    assert.deepEqual(axe.violations.map(v=>v.id),[]);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No page overflow');
    const panel=page.locator('main[aria-labelledby="verify-call-title"]');
    await panel.screenshot({path:path.join(evidence,`${name}-${width}.png`)});
    const fallback=page.getByRole('button',{name:'Use a new 12-digit Agent Pairing Code instead',exact:true});await fallback.focus();await page.keyboard.press('Enter');
    await page.getByText('This verification is no longer active. Your call has no private access.',{exact:true}).waitFor();assert.deepEqual(posts,['fallback']);
    state='pending';await page.reload({waitUntil:'domcontentloaded'});
    await page.getByRole('button',{name:'This wasn’t me',exact:true}).click();
    await page.getByText('This verification is no longer active. Your call has no private access.',{exact:true}).waitFor();assert.deepEqual(posts,['fallback','deny']);
    state='consumed';await page.reload({waitUntil:'domcontentloaded'});await page.getByText('Call verified. Return to your call.',{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Verify this agent call with Face ID / Touch ID',exact:true}).count(),0);
    await ctx.close();console.log(`PASS ${name} ${width}: real page, no navigation approval, keyboard fallback/deny, consumed state, reduced motion, axe, overflow`);
   }
  }finally{await browser.close();}
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
