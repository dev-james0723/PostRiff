/** Local real API + disposable database, synthetic channels/signals/writer only. */
const {chromium,webkit}=require('playwright');
const {randomUUID}=require('node:crypto');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs');const path=require('node:path');
const base='http://127.0.0.1:3397';const root=path.resolve(__dirname,'../..');
const out=path.join(root,'.token-pilot/reports/scout-browser');fs.mkdirSync(out,{recursive:true});
const principal=randomUUID();const headers={'Content-Type':'application/json',Authorization:`Bearer dev:${principal}`,'X-PostRiff-Request':'founder-alpha',Origin:base};
const results=[];
async function call(method,url,body){const r=await fetch(base+url,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});if(!r.ok)throw new Error(`${url}: ${r.status} ${(await r.text()).slice(0,400)}`);return r.json();}
function check(name,value){if(!value)throw new Error(name);results.push({name,ok:true});console.log('PASS',name);}
(async()=>{
 const {workspaceId:w}=await call('POST','/api/auth/verify',{});
 const start=await call('POST',`/api/workspaces/${w}/channels/linkedin/oauth/start`,{capability:'publish'});
 await call('POST',`/api/workspaces/${w}/channels/linkedin/oauth/complete`,{state:new URL(start.authorizeUrl).searchParams.get('state'),code:'good-code'});
 const th=await call('POST',`/api/workspaces/${w}/channels/threads/oauth/start`,{capability:'publish'});
 await call('POST',`/api/workspaces/${w}/channels/threads/oauth/complete`,{state:new URL(th.authorizeUrl).searchParams.get('state'),code:'good-code'});
 const tours=[...fs.readFileSync(path.join(root,'web/src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>m[1]);
 for(const [name,engine] of [['chromium',chromium],['webkit',webkit]]){
  const browser=await engine.launch();
  for(const phone of [false,true]){
   execFileSync(path.join(root,'.token-pilot/validation-venv/bin/python'),[path.join(root,'tests/scout_browser_seed.py'),w]);
   const ctx=await browser.newContext({viewport:phone?{width:390,height:844}:{width:1440,height:960},hasTouch:phone,isMobile:phone,reducedMotion:'reduce',colorScheme:'dark'});
   await ctx.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base},{name:'postriff_theme',value:'rafii',url:base}]);
   await ctx.addInitScript(({principal,tours})=>{localStorage.setItem('postriff-dev-principal',principal);localStorage.setItem('postriff-onboarding',JSON.stringify({completed:{},dismissed:Object.fromEntries(tours.map(x=>[x,1])),nudged:Object.fromEntries(tours.map(x=>[x,1]))}));},{principal,tours});
   const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
   const label=`${name}-${phone?'phone':'desktop'}`;
   await page.goto(base+'/app/weekly?tab=opportunities',{waitUntil:'domcontentloaded',timeout:120000});
   await page.getByRole('region',{name:'Opportunity Flipper'}).waitFor({timeout:120000});
   check(label+' one opportunity no filler',await page.getByText('1 opportunity worth your attention').isVisible());
   check(label+' objective is no promise',await page.getByText('Best suited for: Shares',{exact:true}).isVisible());
   const disclosure=page.getByText('Evidence and limitations',{exact:true});
   if(phone)await disclosure.tap();else{await disclosure.focus();await page.keyboard.press('Enter');}
   check(label+' accessible evidence disclosure',await page.getByText('Creator-normalized audience performance unavailable',{exact:true}).isVisible());
   check(label+' no horizontal overflow',await page.evaluate(()=>document.scrollingElement.scrollWidth<=innerWidth+1));
   await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
   const violations=await page.evaluate(async()=>{const r=await axe.run(document.querySelector('main'));return r.violations.filter(x=>['serious','critical'].includes(x.impact)).map(x=>({id:x.id,nodes:x.nodes.map(n=>n.target)}));});
   check(label+' axe no serious/critical '+JSON.stringify(violations),violations.length===0);
   check(label+' reduced motion',await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches));
   await page.screenshot({path:path.join(out,label+'.png'),fullPage:true});
   const make=page.getByRole('button',{name:'Make post',exact:true});if(phone)await make.tap();else{await make.focus();await page.keyboard.press('Enter');}
   await page.waitForURL(/\/app\/ideas\?source=/,{timeout:30000});
   check(label+' creation retains selected source',new URL(page.url()).searchParams.get('source')?.length>0);
   const snap=await call('GET',`/api/workspaces/${w}`);const source=snap.state.sources.find(s=>s.id===new URL(page.url()).searchParams.get('source'));
   check(label+' source retains destination and provenance',source?.origin?.executionPlan?.platform==='LinkedIn'&&source.origin.evidence.length===2);
   check(label+' zero new console errors '+errors.join(';'),errors.length===0);
   if(!phone){
    execFileSync(path.join(root,'.token-pilot/validation-venv/bin/python'),[path.join(root,'tests/scout_browser_seed.py'),w,'--outcomes']);
    await page.goto(base+'/app/weekly?tab=opportunities');
    await page.getByText('Results from your posts',{exact:true}).click();
    await page.getByText('Evidence and limitations',{exact:true}).click();
    check(label+' observed sequel available',await page.getByRole('button',{name:'Prepare sequel from 7d evidence',exact:true}).isVisible());
    await page.getByRole('button',{name:'Prepare sequel from 7d evidence',exact:true}).click();
    await page.waitForURL(/\/app\/ideas\?source=/);
    const follow=await call('GET',`/api/workspaces/${w}`);
    check(label+' follow-up preserves observed job',follow.state.sources.some(s=>s.origin?.executionPlan?.followupOf?.jobId==='browser-j6'));
    await page.goto(base+'/app/workspace/personalization',{waitUntil:'domcontentloaded',timeout:120000});
    const accept=page.getByRole('button',{name:'Use in planning',exact:true});await accept.waitFor({timeout:120000});await accept.click();
    await page.getByText('Accepted for planning in this account and objective. Your voice is unchanged.',{exact:true}).waitFor();
    const performance=await call('GET',`/api/workspaces/${w}/coworker/performance`);
    check(label+' explicit planning acceptance verified',performance.hypotheses.some(h=>h.planningAccepted));
    check(label+' extended flow zero errors '+errors.join(';'),errors.length===0);
   }
   await ctx.close();
  }
  await browser.close();
 }
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({execution:'local synthetic',results},null,2));console.log(JSON.stringify({passed:results.length}));
})().catch(e=>{console.error(e);process.exit(1);});
