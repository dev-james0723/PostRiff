/** Real local Next -> Python -> PostgreSQL, with synthetic identity and providers only. */
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{randomUUID,createHmac}=require('node:crypto');
const {chromium}=require('playwright');
const base=process.env.RAFII_WEB_URL||'http://127.0.0.1:4469';
assert.equal(new URL(base).hostname,'127.0.0.1');
const out=path.resolve(__dirname,'../../docs/launch-20260923/evidence/finish/browser');
fs.mkdirSync(out,{recursive:true});
const creditMode=process.env.RAFII_TEST_CREDITS==='1';
const principal=randomUUID();
const headers={'Content-Type':'application/json','Authorization':`Bearer dev:${principal}`,'X-PostRiff-Request':'founder-alpha'};
async function call(method,url,body){
 const response=await fetch(base+url,{method,headers,cache:'no-store',body:body===undefined?undefined:JSON.stringify(body)});
 const text=await response.text();assert.ok(response.ok,`${method} ${url}: ${response.status} ${text.slice(0,300)}`);return JSON.parse(text);
}
(async()=>{
 const boot=await call('POST','/api/auth/verify',{plan:'studio'}),wid=boot.workspaceId;
 for(const second of [false,true]){
  const started=await call('POST',`/api/workspaces/${wid}/channels/threads/oauth/start`,{capability:'publish'});
  const state=new URL(started.authorizeUrl).searchParams.get('state');
  await call('POST',`/api/workspaces/${wid}/channels/threads/oauth/complete`,{state,code:second?'good-code-2':'good-code'});
 }
 let snapshot=await call('GET',`/api/workspaces/${wid}`);
 const accounts=snapshot.state.phase2.channels;assert.equal(accounts.length,2);
 snapshot=await call('POST',`/api/workspaces/${wid}/actions`,{expectedRevision:snapshot.revision,action:'p2_folder_save',payload:{name:'Festival',accountIds:accounts.map(a=>a.id),pinned:true,symbol:'music'}});
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const results={principal,wid,steps:[],network:[],requests:[],pageErrors:[],audit:[]};
 let page;
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base},{name:'active_theme',value:'rafii',url:base}]);
  await context.addInitScript(id=>{localStorage.setItem('postriff-dev-principal',id);localStorage.setItem('postriff-onboarding:'+id,JSON.stringify({completed:{},dismissed:{welcome:1},nudged:{}}));localStorage.setItem('postriff.tour.dismissed','1');},principal);
  await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
  page=await context.newPage();page.setDefaultTimeout(20000);page.setDefaultNavigationTimeout(60000);
  page.on('pageerror',error=>results.pageErrors.push(error.message));
  page.on('requestfinished',request=>{ if(new URL(request.url()).pathname.startsWith('/api/')) results.requests.push({path:new URL(request.url()).pathname,method:request.method(),timing:request.timing()}); });
  page.on('response',response=>{if(response.status()>=400)results.network.push({url:new URL(response.url()).pathname,status:response.status()});});
  await page.goto(base+'/app');
  const later=page.getByRole('button',{name:'Not now',exact:true});if(await later.count())await later.click();
  await page.getByLabel('Message',{exact:true}).fill('A small practice habit makes room for creativity.');
  const quickStarts=page.getByRole('button',{name:/More kinds of post/});
  assert.equal(await quickStarts.getAttribute('aria-expanded'),'false');
  await quickStarts.click();assert.equal(await quickStarts.getAttribute('aria-expanded'),'true');
  await quickStarts.click();
  await page.getByRole('button',{name:'Save brief',exact:true}).click();
  await page.reload();
  // The saved brief comes back from this tab's storage after hydration; wait for it instead of reading at load.
  await page.waitForFunction(v=>document.querySelector('textarea[aria-label="Message"]')?.value===v,'A small practice habit makes room for creativity.',{timeout:20000}).catch(()=>{});
  assert.equal(await page.getByLabel('Message',{exact:true}).inputValue(),'A small practice habit makes room for creativity.');
  await page.getByRole('button',{name:'Expand writing space',exact:true}).click();
  await page.getByLabel('Expanded writing space',{exact:true}).fill('A small practice habit makes room for creativity. One step each day.');
  await page.getByRole('dialog').getByRole('button',{name:'Done',exact:true}).click();
  assert.match(await page.getByLabel('Message',{exact:true}).inputValue(),/One step each day/);
  results.steps.push('explicit brief save/reload and expanded editor share text; permissions are not restored');
  await page.getByRole('button',{name:/^Choose channels,/}).click();
  await page.getByRole('checkbox',{name:/^Festival/}).click();
  const done=page.getByRole('button',{name:/^Done/});await done.click();
  await page.getByLabel('Message',{exact:true}).fill('A small practice habit makes room for creativity.');
  assert.equal(await page.getByRole('checkbox',{name:'Allow public quotes from my own writing',exact:true}).isChecked(),false);
  if(creditMode) await page.getByLabel('Maximum credits for this draft',{exact:true}).fill('45');
  await page.getByRole('button',{name:/^Generate drafts/}).click();
  await page.waitForURL(/\/app\?run=/,{timeout:30000});
  await page.getByRole('button',{name:'Save as drafts',exact:true}).waitFor();
  const runId=new URL(page.url()).searchParams.get('run');
  const run=await call('GET',`/api/workspaces/${wid}/ideas/runs/${runId}/events?cursor=0`);
  assert.deepEqual(new Set(run.artifact.variants.map(v=>v.channelId)),new Set(accounts.map(a=>a.id)));
  assert.equal(run.artifact.variants.length,2);
  results.steps.push('two connected accounts generate distinct identity-bound variants');
  if(creditMode){const usage=await call('GET',`/api/workspaces/${wid}/usage`);assert.equal(usage.credits.availableMilliCredits,47000);assert.equal(usage.credits.heldMilliCredits,0);assert.equal(usage.credits.usedMilliCredits,3000);results.steps.push('real credit quote, reserve and settlement: 50 to 47 credits, with zero held');}
  await page.getByLabel('Edit draft preview',{exact:true}).fill('This is the manually edited draft for one specific account.');
  await page.getByRole('button',{name:'Save as drafts',exact:true}).click();
  await page.getByRole('link',{name:'Open drafts',exact:true}).waitFor();
  await page.reload();await page.getByRole('link',{name:'Open drafts',exact:true}).waitFor();
  assert.equal(await page.getByLabel('Edit draft preview',{exact:true}).inputValue(),'This is the manually edited draft for one specific account.');
  snapshot=await call('GET',`/api/workspaces/${wid}`);
  const edited=snapshot.state.variants.filter(v=>v.text==='This is the manually edited draft for one specific account.');
  assert.equal(edited.length,1);assert.ok(accounts.some(a=>a.id===edited[0].channelId));
  assert.equal(snapshot.state.phase2.jobs.length,0);
  results.steps.push('save, edit, reload preserves one-account edit without any publishing job');
  if(creditMode){
    await page.getByRole('link',{name:'Open conversation',exact:true}).click();
    await page.waitForURL(/\/app\/agent\//);
    await page.getByRole('link',{name:'Open Queue',exact:true}).waitFor();
    await page.getByLabel('Message',{exact:true}).fill('Create another caption about daily creative practice.');
    await page.getByLabel('Maximum credits for this draft',{exact:true}).fill('45');
    const dispatched=page.waitForResponse(response=>response.request().method()==='POST'&&new URL(response.url()).pathname.endsWith('/turns'));
    await page.getByRole('button',{name:'Send',exact:true}).click();
    const response=await dispatched;assert.equal(response.ok(),true);
    let used;
    for(let retry=0;retry<60;retry++){
      used=await call('GET',`/api/workspaces/${wid}/usage`);
      if(used.credits.usedMilliCredits===6000&&used.credits.availableMilliCredits===44000&&used.credits.heldMilliCredits===0)break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    assert.deepEqual([used.credits.availableMilliCredits,used.credits.usedMilliCredits,used.credits.heldMilliCredits],[44000,6000,0]);
    results.steps.push('conversation follow-up uses its own approved quote: 47 to 44 credits');
    await page.goto(base+'/app?run='+runId);
    await page.getByRole('link',{name:'Open drafts',exact:true}).waitFor();
  }
  if(!creditMode){
    // Recurring drafting lives in the Automation builder: a custom schedule saved as a draft stays unactivated.
    await page.goto(base+'/app/automations');
    await page.getByRole('heading',{name:'Automations',level:1}).waitFor();
    await page.getByRole('button',{name:'New automation'}).first().click();
    const builder=page.getByRole('dialog',{name:/automation/i}).first();
    await builder.getByLabel('Name',{exact:true}).fill('Daily creative practice');
    await builder.getByLabel('What should each draft be about?').fill('Build a daily creative practice');
    await builder.getByLabel('Who is it for?').fill('Creative beginners');
    await builder.getByRole('tab',{name:/When/}).click();
    for(const day of ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']){
     const button=builder.getByRole('button',{name:day,exact:true});
     if(((await button.getAttribute('aria-pressed'))==='true')!==(day==='Thursday'))await button.click();
    }
    await builder.getByLabel('At',{exact:true}).fill('20:45');
    await builder.getByRole('tab',{name:/Where/}).click();
    await builder.getByRole('button',{name:'Choose accounts or folders'}).click();
    const bloom=page.getByRole('dialog').filter({has:page.getByRole('checkbox',{name:/^Festival/})}).last();
    await bloom.getByRole('checkbox',{name:/^Festival/}).click();
    await bloom.getByRole('button',{name:/^Done/}).click();
    await builder.getByRole('tab',{name:/Review/}).click();
    await builder.getByLabel('Writer').selectOption('deterministic-preview');
    await builder.getByLabel('Cost limit per run (USD)').fill('0');
    await builder.getByRole('button',{name:'Save as draft',exact:true}).click();
    await builder.waitFor({state:'hidden',timeout:30000});
    const planning=await call('GET',`/api/workspaces/${wid}`);
    const task=planning.state.raffi.campaignPlanning.recurringTasks.findLast(t=>t.name==='Daily creative practice');
    const days=task.schedule.weekdays??(task.schedule.weekday?[task.schedule.weekday]:[]);
    assert.deepEqual(days,['Thursday']);assert.equal(task.schedule.localTime,'20:45');assert.equal(task.status,'draft');
    await page.goto(base+'/app');
    const planner=page.locator('section[aria-label="Automations and Rafii suggestions"]');
    // Home is server-rendered: wait until React has attached the button's handler before clicking it.
    await planner.getByRole('button',{name:'Refresh',exact:true}).waitFor();
    await page.waitForFunction(()=>[...document.querySelectorAll('section[aria-label="Automations and Rafii suggestions"] button')].some(b=>b.textContent.trim()==='Refresh'&&Object.keys(b).some(k=>k.startsWith('__reactProps'))));
    await planner.getByRole('button',{name:'Refresh',exact:true}).click();
    await planner.getByRole('button',{name:'Snooze 1 day',exact:true}).first().click();
    await planner.getByRole('button',{name:'Snooze 1 day',exact:true}).waitFor({state:'hidden'});
    const snoozed=await call('GET',`/api/workspaces/${wid}`);
    assert.ok(snoozed.state.raffi.suggestions.some(item=>item.status==='snoozed'));
    results.steps.push('custom recurring schedule saved as a draft automation stays unactivated; suggestion snooze persists');
  }
  for(const width of [390,768,1440]){
   await page.setViewportSize({width,height:1000});
   await page.screenshot({path:path.join(out,`${creditMode ? "credit-" : ""}journey-${width}.png`),fullPage:true});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  }
  await page.goto(base+'/app/channels');await page.getByRole('heading',{name:'Folders',exact:true}).waitFor();
  await page.getByRole('button',{name:'New folder',exact:true}).first().click();
  await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'});
  if(creditMode){
    await page.goto(base+'/app/account/billing');
    await page.getByRole('button',{name:/1,000 credits/}).click();
    await page.getByRole('heading',{name:'Confirm purchase',exact:true}).waitFor();
    await page.route('https://checkout.stripe.com/**',route=>route.fulfill({status:200,contentType:'text/html',body:'<title>Synthetic checkout</title><h1>Synthetic payment only</h1>'}));
    let order;
    await page.route('**/billing/credit-checkout',async route=>{
      assert.equal(new URL(route.request().url()).origin,base);
      const response=await route.fetch();assert.equal(response.ok(),true);
      order=await response.json();
      await route.fulfill({response});
    });
    await page.getByRole('button',{name:'Continue to Stripe',exact:true}).click();
    await page.waitForURL(/checkout\.stripe\.com/);assert.ok(order?.orderId);
    assert.equal((await call('GET',`/api/workspaces/${wid}/usage`)).credits.availableMilliCredits,44000);
    const now=Math.floor(Date.now()/1000),event={id:'evt_browser_'+randomUUID(),type:'checkout.session.completed',created:now,livemode:false,data:{object:{id:order.sessionId,mode:'payment',payment_status:'paid',payment_intent:'pi_browser_'+randomUUID(),amount_total:1000,currency:'usd',metadata:{credit_order_id:order.orderId}}}};
    const raw=JSON.stringify(event),signature=createHmac('sha256','local-test-payment-signature').update(`${now}.`+raw).digest('hex');
    for(let repeat=0;repeat<2;repeat++){
      const receipt=await fetch(base+'/api/billing/webhook',{method:'POST',headers:{'Content-Type':'application/json','Stripe-Signature':`t=${now},v1=${signature}`},body:raw});
      assert.equal(receipt.ok,true);const result=await receipt.json();assert.equal(result.outcome,repeat?'duplicate':'applied');
    }
    await page.goto(base+'/app/account/billing?creditCheckout=returned');
    await page.getByRole('button',{name:'Refresh balance',exact:true}).click();
    assert.equal((await call('GET',`/api/workspaces/${wid}/usage`)).credits.availableMilliCredits,1044000);
    results.steps.push('top-up UI, synthetic signed payment and replay: exactly 1000 credits added once, never before payment');
  }
  await page.goto(base+'/app');
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  results.audit=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}));});
  assert.deepEqual(results.pageErrors,[]);
  assert.equal(results.audit.filter(v=>['critical','serious'].includes(v.impact)).length,0,'critical/serious accessibility violations');
  results.functional='pass';
 }catch(error){results.functional='fail';results.error=String(error.stack||error);if(page)await page.screenshot({path:path.join(out,creditMode?'credit-journey-failure.png':'journey-failure.png'),fullPage:true}).catch(()=>{});throw error;}
 finally{fs.writeFileSync(path.join(out,creditMode?'credit-journey.json':'journey.json'),JSON.stringify(results,null,2));await browser.close();}
 console.log(JSON.stringify(results,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
