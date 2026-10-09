/** Actual app/API/PostgreSQL with fake transports. No real subscription, message or phone call. */
const {chromium,webkit}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto'),{execFileSync}=require('node:child_process');
const base=process.env.RAFII_WEB_URL || 'http://localhost:3293';
if (!['localhost','127.0.0.1'].includes(new URL(base).hostname)) throw Error('Loopback harness only');
const root=path.resolve(__dirname,'../..');
const out=process.env.RAFII_NOTIFICATION_EVIDENCE_DIR
 ? path.resolve(process.env.RAFII_NOTIFICATION_EVIDENCE_DIR)
 : path.join(root,'docs/design/rafii-live-agent/evidence/notifications');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const results=[];
 for (const [name,engine] of [['chromium',chromium],['webkit',webkit]]) {
  const principal=randomUUID(),headers={Authorization:'Bearer dev:'+principal,'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha'};
  async function api(method,p,body) {const r=await fetch(base+p,{method,headers,...(body===undefined?{}:{body:JSON.stringify(body)})});assert.ok(r.ok,`${r.status} ${await r.clone().text()}`);return r.json();}
  const wid=(await api('POST','/api/auth/verify',{plan:'assist'})).workspaceId;
  const phoneInfo=await api('GET',`/api/workspaces/${wid}/phone`);assert.equal(phoneInfo.execution,'fake');
  const fixture=(action)=>JSON.parse(execFileSync(process.env.RAFII_PYTHON || '/tmp/rafii-phone-env/bin/python',['tests/phase2/notification_browser_fixture.py',action,process.env.RAFII_HARNESS_PG_PORT || '55754',principal,wid],{cwd:root,env:{...process.env,PYTHONPATH:'src:tests'},encoding:'utf8'}).trim().split('\n').at(-1));
  const browser=await engine.launch({headless:true});
  let page;
  try {
   const ctx=await browser.newContext({viewport:{width:1280,height:1000}});
   await ctx.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base},{name:'postriff_theme',value:'rafii',url:base}]);
   const tourIds=[...fs.readFileSync(path.join(root,'web/src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>m[1]);
   await ctx.addInitScript(({principal,tourIds})=>{localStorage.setItem('postriff-dev-principal',principal);localStorage.setItem('postriff-onboarding',JSON.stringify({completed:{},dismissed:Object.fromEntries(tourIds.map(t=>[t,1])),nudged:{}}));},{principal,tourIds});
   page=await ctx.newPage();let calls=0,acks=0;
   page.on('pageerror',e=>console.error(name,e.message));
   page.on('response',async r=>{if(r.status()>=400 && r.url().includes('/api/')) console.error(name,r.status(),new URL(r.url()).pathname,await r.text());});
   page.on('request',r=>{const p=new URL(r.url()).pathname;if(r.method()==='POST' && /\/phone\/calls$/.test(p))calls++;if(r.method()==='POST' && /\/notifications\/acknowledge$/.test(p))acks++;});
   await page.goto(base+'/app/account/notifications',{waitUntil:'domcontentloaded'});
   const texts=page.locator('section[aria-labelledby="notifications-texts-heading"]'),phone=page.locator('#phone-mode');
   await texts.getByText('Verify a number in Phone Mode to receive texts.',{exact:true}).waitFor({timeout:90000});
   assert.equal(await texts.getByLabel('Text message delivery').inputValue(),'off');
   await texts.getByRole('link',{name:'Verify a number',exact:true}).click();
   assert.equal(new URL(page.url()).hash,'#phone-mode');
   await phone.getByLabel('Phone number with country code').fill('+12025550123');
   await phone.getByRole('button',{name:'Send verification code',exact:true}).click();
   await phone.getByLabel('Verification code',{exact:true}).fill('123456');
   await phone.getByRole('button',{name:'Verify phone number',exact:true}).click();
   await texts.getByText('Verified number: •••• 0123',{exact:true}).waitFor();
   assert.equal(await texts.getByLabel('Text message delivery').inputValue(),'off','Verification never grants text consent');
   await phone.getByRole('switch',{name:'Enable Call Rafii',exact:true}).click();
   assert.equal((await api('GET',`/api/workspaces/${wid}/notification-preferences`)).sms.consented,false);
   await texts.getByLabel('Text message delivery').selectOption('important_only');
   await texts.getByRole('switch',{name:'Include account-change texts',exact:true}).waitFor();
   assert.equal((await api('GET',`/api/workspaces/${wid}/notification-preferences`)).sms.consented,true);
   assert.equal((await texts.innerText()).includes('+12025550123'),false);
   const event=fixture('seed');const push=event.deliveries.find(d=>d.channel==='push');
   assert.ok(push);assert.equal(event.deliveries.find(d=>d.channel==='sms').status,'pending');
   const acknowledgement=page.waitForResponse(r=>r.url().endsWith('/notifications/acknowledge') && r.status()===200);
   await page.goto(base+'/app/channels?notification='+push.deliveryId,{waitUntil:'domcontentloaded'});
   await acknowledgement;
   assert.equal(fixture('state').deliveries.find(d=>d.channel==='sms').status,'cancelled');assert.ok(acks>=1);
   await page.goto(base+'/app/account/notifications',{waitUntil:'domcontentloaded'});
   await texts.getByRole('switch',{name:'Include account-change texts',exact:true}).waitFor();
   for (const width of [1280,375]) for (const scheme of ['light','dark']) {
    await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:scheme});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal overflow');
    await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
    const violations=await page.evaluate(async()=> (await axe.run('section[aria-labelledby="notifications-texts-heading"]',{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>v.id));
    assert.deepEqual(violations,[]);
    await page.screenshot({path:path.join(out,`${name}.${scheme}.${width}.settings.png`),fullPage:true});
   }
   fixture('stop');await page.reload({waitUntil:'domcontentloaded'});
   await texts.getByText(/Your provider stopped text messages/).waitFor();
   assert.equal(await texts.getByLabel('Text message delivery').inputValue(),'off');
   assert.equal((await api('GET',`/api/workspaces/${wid}/phone`)).preferences.enabled,true);
   assert.equal(calls,0,'Verification, text opt-in and notification navigation never dial');
   await texts.screenshot({path:path.join(out,`${name}.stop-settings.png`)});
   results.push({browser:name,status:'PASS',checks:['shared masked verification','SMS off despite Phone verification/enabled','explicit text consent','authenticated Push navigation cancels durable SMS','provider STOP settings state','Phone remains enabled','desktop/mobile/light/dark','axe WCAG2A/AA','zero call requests']});
  } catch(e) {if(page){console.error((await page.locator('section[aria-labelledby="notifications-texts-heading"]').innerText().catch(()=>'')));await page.screenshot({path:path.join(out,`${name}.failure.png`),fullPage:true});}throw e;} finally {await browser.close();}
 }
 fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({execution:'actual local UI/API/SQL with fake transports and synthetic STOP state',realSMS:0,realCalls:0,results},null,2));
 console.log(JSON.stringify(results));
})().catch(e=>{console.error(e);process.exitCode=1;});
