/** Real local Next (production build) -> hosted Python -> disposable DB. Only identity/providers are synthetic.
 *
 * Rafii v9 flows, per width (1440, 1024, 390, 320) after a first-user pass:
 *   - first user: the welcome dialog, "Not now" remembered across a reload, an idea drafted from Home whose
 *     conversation survives a reload;
 *   - the language picker opened and used with the keyboard only, focus returned on Escape;
 *   - an automation set up by asking Rafii on Home, then edited, paused, resumed and cancelled in the Automations hub,
 *     each surviving a reload (the old Home campaign planner's recurrence controls);
 *   - keyboard Tab order inside the automation editor, axe (WCAG 2 A/AA) on the hub, no horizontal scroll;
 *   - a writing sample retained, allowed for analysis and a writer, described, then revoked and removed;
 *   - at 1440: private server rendering (no shared cache, another member's workspace never rendered, a forged route
 *     hint ignored, nothing private for a signed-out visitor).
 * Nothing is published: the final snapshot has no publication jobs.
 */
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const {mkdirSync,writeFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.CONSUMER_WEB_URL || 'http://127.0.0.1:4439';
assert.equal(new URL(base).hostname,'127.0.0.1');
const out=resolve(__dirname,'../../docs/consumer-ready/evidence');mkdirSync(out,{recursive:true});
const HOME_HEADING=/What.s the idea/;
const overflowing=page=>page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);

async function signIn(browser,{width,principal,welcome=false}) {
 const context=await browser.newContext({viewport:{width,height:welcome?844:1000},reducedMotion:'reduce'});
 await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base}]);
 await context.addInitScript(([id,skipWelcome])=>{
  localStorage.setItem('postriff-dev-principal',id);
  if(skipWelcome)localStorage.setItem('postriff-onboarding:'+id,JSON.stringify({completed:{},dismissed:{welcome:1},nudged:{}}));
 },[principal,!welcome]);
 // No mocked API responses. Only prevent external browser requests.
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 return context;
}

async function home(page) {
 await page.goto(base+'/app');
 await page.getByRole('heading',{level:1,name:HOME_HEADING}).waitFor({timeout:60000});
 await page.waitForFunction(()=>document.querySelector('[aria-label="Message"]')?.disabled===false,null,{timeout:60000});
}

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 const results=[]; const audits=[];
 try {
  // First-time identity is synthetic, but welcome/bootstrap and drafting use the actual UI/API/DB.
  const firstId=randomUUID(),first=await signIn(browser,{width:390,principal:firstId,welcome:true});
  const welcome=await first.newPage();
  await welcome.goto(base+'/app');
  await welcome.getByRole('dialog').filter({has:welcome.getByRole('heading',{name:/Welcome to/})}).waitFor({timeout:60000});
  await welcome.getByRole('button',{name:'Not now',exact:true}).click();
  await welcome.getByRole('dialog').waitFor({state:'hidden'});
  await welcome.reload();await welcome.getByLabel('Message',{exact:true}).waitFor();
  assert.equal(await welcome.getByRole('heading',{name:/Welcome to/}).count(),0);
  await welcome.getByLabel('Message',{exact:true}).fill('Write one short English post for Threads about making time to practise music. Do not invent events or dates.');
  const drafted=welcome.waitForResponse(r=>r.url().includes('/ideas/quick-start')&&r.request().method()==='POST',{timeout:120000});
  await welcome.getByRole('button',{name:/^Generate drafts/}).click();
  const draft=await (await drafted).json();
  assert.ok(draft.conversationId,'the idea opened a conversation');
  await welcome.getByRole('region',{name:'Generated drafts'}).waitFor({timeout:120000});
  await welcome.goto(base+'/app/agent/'+draft.conversationId);
  await welcome.getByText(/candidate variants from/).first().waitFor({timeout:60000});
  const conversationUrl=welcome.url();await welcome.reload();
  await welcome.getByText(/candidate variants from/).first().waitFor({timeout:60000});
  assert.equal(welcome.url(),conversationUrl);
  await welcome.screenshot({path:resolve(out,'first-user-draft-390.png'),fullPage:true});
  results.push({width:390,firstUserWelcome:true,dismissalPersisted:true,uiDraftGeneratedAndReloaded:true,model:'deterministic fixture',realIdentityVerified:false});
  await first.close();

  for(const width of [1440,1024,390,320]) {
   const principal=randomUUID();const context=await signIn(browser,{width,principal});
   const page=await context.newPage();page.setDefaultTimeout(30000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await home(page);
   // The language picker with the keyboard only: open, choose French, apply; reopen, Escape returns focus.
   const languageButton=page.locator('button[aria-haspopup="dialog"]').filter({hasText:'Language'}).first();
   await languageButton.focus();await page.keyboard.press('Enter');
   const dialog=page.getByRole('dialog');await dialog.waitFor();
   const destination=dialog.getByRole('button',{name:/^Output language for /}).first();
   await destination.focus();await page.keyboard.press('Enter');
   const search=dialog.getByRole('combobox',{name:'Search languages or regions',exact:true});
   await search.waitFor();await search.fill('French');
   // Options read native name first ("Français (France)"), then the English name.
   const french=dialog.getByRole('option',{name:/French/}).first();await french.waitFor();
   await french.focus();await page.keyboard.press('Enter');
   const apply=dialog.getByRole('button',{name:/^Apply/});await apply.focus();await page.keyboard.press('Enter');
   await dialog.waitFor({state:'hidden'});
   await page.waitForFunction(()=>[...document.querySelectorAll('button[aria-haspopup="dialog"]')].some(b=>/Language/.test(b.textContent)&&/French|Français/.test(b.textContent+(b.getAttribute('aria-label')||''))),null,{timeout:15000});
   await languageButton.focus();await page.keyboard.press('Enter');await dialog.waitFor();
   await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
   await page.waitForFunction(()=>{const a=document.activeElement;return a?.getAttribute('aria-haspopup')==='dialog'&&/Language/.test(a.textContent);},null,{timeout:15000});

   // An automation, set up by asking Rafii (drafts only: nothing is scheduled or published).
   const title='Autumn concert '+width;
   await page.getByLabel('Message',{exact:true}).fill(`Every Monday at 9am draft me a post about ${title}`);
   const answered=page.waitForResponse(r=>r.url().includes('/ideas/quick-start')&&r.request().method()==='POST',{timeout:120000});
   await page.getByRole('button',{name:/^Generate drafts/}).click();
   const reply=await (await answered).json();
   assert.equal(reply.status,'automation');assert.equal(reply.automation?.status,'active');
   const taskId=reply.automation.taskId,name=reply.automation.name;
   await page.goto(base+'/app/automations');
   await page.getByRole('heading',{name:'Automations',level:1}).waitFor({timeout:60000});
   const card=()=>page.locator('article').filter({has:page.getByRole('heading',{name})});
   await card().waitFor();await page.reload();await card().waitFor();
   // Edit (returns it to draft) and activate again; Tab moves through the editor's fields.
   await card().getByRole('button',{name:'Edit'}).click();
   const edit=page.getByRole('dialog',{name:/automation/i}).first();
   const nameField=edit.getByLabel('Name',{exact:true});await nameField.waitFor();
   await nameField.fill(name+' reviewed');
   await nameField.focus();await page.keyboard.press('Tab');
   assert.equal(await page.evaluate(()=>{const a=document.activeElement;return Boolean(a&&a.closest('[role="dialog"]')&&a.getAttribute('aria-label')!=='Name'&&!(a.labels&&[...a.labels].some(l=>l.textContent.trim()==='Name')));}),true,'Tab moves on inside the editor');
   await edit.getByRole('tab',{name:/Review/}).click();
   await edit.getByRole('button',{name:'Save as draft'}).click();
   await edit.waitFor({state:'hidden',timeout:30000});
   const reviewed=()=>page.locator('article').filter({has:page.getByRole('heading',{name:name+' reviewed'})});
   await reviewed().getByRole('button',{name:'Activate'}).click();
   await reviewed().getByRole('button',{name:'Pause'}).waitFor();
   await page.reload();await reviewed().getByRole('button',{name:'Pause'}).click();
   await reviewed().getByRole('button',{name:'Resume'}).waitFor();
   await page.reload();await reviewed().getByRole('button',{name:'Resume'}).click();
   await reviewed().getByRole('button',{name:'Pause'}).waitFor();
   assert.equal(await overflowing(page),false,'no horizontal scroll on the hub');
   await page.addScriptTag({path:require.resolve('axe-core/axe.min.js',{paths:[process.env.PLAYWRIGHT_MODULE || resolve(__dirname,'../node_modules')]})});
   const audit=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,help:v.help,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),passes:r.passes.length};});
   audits.push({width,page:'automations',...audit});
   writeFileSync(resolve(out,'browser-accessibility.json'),JSON.stringify({execution:'local Chromium axe-core; reduced motion; keyboard tab; no human conformance claim',audits},null,2));
   await page.screenshot({path:resolve(out,`durable-automation-${width}.png`),fullPage:true});
   await reviewed().getByRole('button',{name:'Cancel automation'}).click();
   const confirm=page.getByRole('dialog').filter({hasText:'No further drafts will be prepared'});await confirm.waitFor();
   await confirm.getByRole('button',{name:'Cancel automation'}).click();
   await confirm.waitFor({state:'hidden'});
   await page.reload();await page.getByRole('heading',{name:'Automations',level:1}).waitFor();
   assert.equal(await reviewed().count(),0,'a cancelled automation leaves the active list');

   // A writing sample: retained, allowed for local analysis and a writer, described, then revoked and removed.
   await page.goto(base+'/app/workspace/brand');
   const sample='先聽一聽。\nA small musical observation. 🎵';
   await page.getByLabel('Writing sample',{exact:true}).fill(sample);
   await page.getByRole('checkbox',{name:'Confirm manual writing sample authorship and retention'}).check();
   await page.getByRole('button',{name:'Retain samples',exact:true}).click();
   const row=page.locator('li').filter({has:page.getByText(sample,{exact:true})});await row.waitFor();
   await row.getByRole('checkbox').click();
   await row.getByRole('checkbox',{checked:true}).waitFor();
   await row.getByRole('button',{name:'Allow local analysis',exact:true}).click();
   await row.getByText(/Allowed for/).waitFor();
   const writers=await row.getByRole('combobox').locator('option').evaluateAll(options=>options.map(o=>o.value));
   const writer=writers.includes('local-cli')?'local-cli':writers.find(v=>v)||writers[0];
   await row.getByRole('combobox').selectOption(writer);
   await row.getByRole('button',{name:'Allow this writer to use style'}).click();
   await row.getByText(/Allowed for.*generation/).waitFor();
   await page.reload();await page.getByText(sample,{exact:true}).waitFor();
   await page.getByRole('button',{name:'Describe local writing statistics',exact:true}).click();
   await page.getByText('A provisional voice profile is ready for review. It is not active yet.',{exact:true}).waitFor();
   await row.getByRole('button',{name:'Revoke & remove text',exact:true}).click();
   await row.getByRole('button',{name:'Confirm revoke',exact:true}).click();
   await page.waitForFunction(text => ![...document.querySelectorAll('p,blockquote')].some(el => el.textContent === text),sample);
   await page.reload();assert.equal(await page.getByText(sample,{exact:true}).count(),0);
   assert.equal(await overflowing(page),false,'no horizontal scroll on Brand');

   const headers={Authorization:'Bearer dev:'+principal,Origin:base};
   const spaces=await (await context.request.get(base+'/api/workspaces',{headers})).json();
   const wid=spaces.workspaces[0].workspaceId;
   if(width===1440) {
    const htmlResponse=await context.request.get(base+'/app');const html=await htmlResponse.text();
    assert.match(htmlResponse.headers()['cache-control'],/no-store/);
    assert.match(html,/<h1[^>]*>[^<]*What.s the idea/);
    assert.ok(html.includes(wid),'authenticated workspace is bootstrapped');
    assert.equal(html.includes('Bearer dev:'),false);assert.equal(html.includes('dev:'+principal),false);
    const stranger=randomUUID(),other=await browser.newContext({javaScriptEnabled:false});
    await other.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:stranger,url:base},{name:'postriff_workspace',value:wid,url:base}]);
    const bootstrap=await other.request.post(base+'/api/auth/verify',{headers:{Authorization:'Bearer dev:'+stranger,Origin:base},data:{plan:'studio'}});assert.ok(bootstrap.ok());
    const own=await (await other.request.get(base+'/api/workspaces',{headers:{Authorization:'Bearer dev:'+stranger}})).json();
    const privatePage=await other.newPage();await privatePage.goto(base+'/app');
    await privatePage.getByRole('heading',{level:1,name:HOME_HEADING}).waitFor();
    const ownHtml=await privatePage.content();assert.ok(ownHtml.includes(own.workspaces[0].workspaceId));assert.equal(ownHtml.includes(wid),false);assert.equal(ownHtml.includes(title),false);
    const forged=await other.request.get(base+'/app/account',{headers:{'x-postriff-home-render':'1'}});assert.equal((await forged.text()).includes(own.workspaces[0].workspaceId),false);
    await other.close();
    const anonymous=await browser.newContext();const anon=await anonymous.request.get(base+'/app');assert.equal((await anon.text()).includes(wid),false);await anonymous.close();
    results.push({privateSSR:true,noSharedCache:true,foreignSelectionRejected:true,anonymousPrivateData:false,forgedRouteHintRejected:true,jsDisabledFirstPaint:true});
   }
   const snap=await (await context.request.get(base+'/api/workspaces/'+wid,{headers})).json();
   const task=snap.state.raffi.campaignPlanning.recurringTasks.find(t=>t.id===taskId);
   assert.equal(task.name,name+' reviewed');assert.equal(task.status,'cancelled');assert.equal(task.version,2);
   assert.equal(snap.state.sources.find(s=>s.kind==='voice_sample').text,'');
   assert.equal(snap.state.phase2.jobs.length,0);
   assert.deepEqual(errors,[]);
   await page.screenshot({path:resolve(out,`durable-voice-${width}.png`),fullPage:true});
   results.push({width,languagePickerKeyboard:true,automationFromChat:true,automationControlsPersisted:true,keyboardTab:true,voiceGrantPersisted:true,revocationPersisted:true,pageErrors:errors.length,publicationJobs:0});
   await context.close();
  }
  writeFileSync(resolve(out,'durable-browser.json'),JSON.stringify({status:'PASS',execution:'real local frontend/API/PostgreSQL; synthetic identity/provider; no paid calls',results},null,2)+'\n');
  console.log(JSON.stringify(results));
  assert.deepEqual(audits.flatMap(a=>a.violations.filter(v=>['critical','serious'].includes(v.impact))),[], 'Unresolved serious accessibility failures');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
