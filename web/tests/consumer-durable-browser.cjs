/** Real local Next -> hosted Python -> disposable DB. Only identity/providers are synthetic. Rafii v9 flows. */
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const {mkdirSync,writeFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.CONSUMER_WEB_URL || 'http://127.0.0.1:4439';
assert.equal(new URL(base).hostname,'127.0.0.1');
const out=resolve(__dirname,'../../docs/consumer-ready/evidence');mkdirSync(out,{recursive:true});
const HOME_TITLE='What’s the idea today?';
// Home's setting buttons (Language, Model, …) open a dialog; the kicker text names them.
const settingButton=(page,kicker)=>page.locator('button[aria-haspopup="dialog"]').filter({hasText:kicker}).first();
// Home is server-rendered, so its controls are visible before React attaches handlers; wait for that first.
// The locator is re-resolved on every check, because React may replace a server-rendered node.
const hydrated=async(page,locator,timeout=20000)=>{
 await locator.waitFor({timeout});const end=Date.now()+timeout;
 while(!(await locator.evaluate(el=>Object.keys(el).some(k=>k.startsWith('__reactProps'))).catch(()=>false))){
  if(Date.now()>end) throw new Error('Not hydrated: '+locator);
  await page.waitForTimeout(100);
 }
};
const draftsReady=page=>page.waitForFunction(()=>/ready · yours to edit/.test(document.querySelector('section[aria-label="Generated drafts"] [role="status"]')?.textContent ?? ''),null,{timeout:120000});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 const results=[]; const audits=[];
 try {
  // First-time identity is synthetic, but welcome/bootstrap use the actual UI/API/DB.
  const firstId=randomUUID(),first=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
  await first.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:firstId,url:base}]);
  await first.addInitScript(id=>localStorage.setItem('postriff-dev-principal',id),firstId);
  await first.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
  const welcome=await first.newPage();
  await welcome.goto(base+'/app');
  await welcome.getByRole('dialog').filter({has:welcome.getByRole('heading',{name:'Welcome to Rafii'})}).waitFor();
  await welcome.getByRole('button',{name:'Not now',exact:true}).click();
  await welcome.getByRole('dialog').waitFor({state:'hidden'});
  await welcome.reload();await hydrated(welcome,welcome.getByLabel('Message',{exact:true}));
  assert.equal(await welcome.getByRole('heading',{name:'Welcome to Rafii'}).count(),0);
  await welcome.getByLabel('Message',{exact:true}).fill('Write one short English post for Threads about making time to practise music. Do not invent events or dates.');
  await welcome.getByRole('button',{name:/^Generate drafts/}).click();
  // Rafii v9 keeps the drafts on Home and records the run in the address, so a reload brings them back.
  await welcome.waitForURL(/\/app\?run=/,{timeout:120000});
  await draftsReady(welcome);
  const runUrl=welcome.url();await welcome.reload();
  await draftsReady(welcome);
  assert.equal(welcome.url(),runUrl);
  await welcome.screenshot({path:resolve(out,'first-user-draft-390.png'),fullPage:true});
  results.push({width:390,firstUserWelcome:true,dismissalPersisted:true,uiDraftGeneratedAndReloaded:true,model:'deterministic fixture',realIdentityVerified:false});
  await first.close();
  for(const width of [1440,1024,390,320]) {
   const principal=randomUUID();const context=await browser.newContext({viewport:{width,height:1000},reducedMotion:'reduce'});
   await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base}]);
   await context.addInitScript(id=>{localStorage.setItem('postriff-dev-principal',id);localStorage.setItem('postriff-onboarding:'+id,JSON.stringify({completed:{},dismissed:{welcome:1},nudged:{}}));},principal);
   // No mocked API responses. Only prevent external browser requests.
   await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
   const headers={Authorization:'Bearer dev:'+principal,Origin:base,'X-PostRiff-Request':'founder-alpha'};
   const api=async(method,url,data)=>{const r=await context.request.fetch(base+url,{method,headers,data});assert.ok(r.ok(),`${method} ${url} → ${r.status()}`);return r.json();};
   // A synthetic connected account and a folder, so an automation has somewhere to draft for.
   const boot=await api('POST','/api/auth/verify',{plan:'studio'});const wid=boot.workspaceId;
   const started=await api('POST',`/api/workspaces/${wid}/channels/threads/oauth/start`,{capability:'publish'});
   await api('POST',`/api/workspaces/${wid}/channels/threads/oauth/complete`,{state:new URL(started.authorizeUrl).searchParams.get('state'),code:'good-code'});
   let snap=await api('GET',`/api/workspaces/${wid}`);
   await api('POST',`/api/workspaces/${wid}/actions`,{expectedRevision:snap.revision,action:'p2_folder_save',payload:{name:'Festival',accountIds:snap.state.phase2.channels.map(a=>a.id),pinned:true,symbol:'music'}});
   const page=await context.newPage();page.setDefaultTimeout(20000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base+'/app');await hydrated(page,page.getByLabel('Message',{exact:true}));
   // Open the language dialog using only the keyboard; choose a language, then check focus restoration.
   const languageButton=settingButton(page,'Language');
   await hydrated(page,languageButton);await languageButton.focus();await page.keyboard.press('Enter');
   const languageDialog=page.getByRole('dialog');await languageDialog.waitFor();
   const row=languageDialog.getByRole('button',{name:/^Output language for /}).first();
   await row.focus();await page.keyboard.press('Enter');
   const search=languageDialog.getByRole('combobox',{name:'Search languages or regions'});
   await search.waitFor();await search.fill('French');
   const french=languageDialog.getByRole('option',{name:/French/}).first();await french.waitFor();
   await french.focus();await page.keyboard.press('Enter');
   const apply=languageDialog.getByRole('button',{name:/^Apply/});await apply.focus();await page.keyboard.press('Enter');
   await languageDialog.waitFor({state:'hidden'});
   await page.waitForFunction(()=>[...document.querySelectorAll('button[aria-haspopup="dialog"]')].some(b=>/Language/.test(b.textContent)&&/French|Per destination|languages/.test(b.textContent)));
   await languageButton.focus();await page.keyboard.press('Enter');await languageDialog.waitFor();
   await page.keyboard.press('Escape');await languageDialog.waitFor({state:'hidden'});
   await page.waitForFunction(()=>document.activeElement?.getAttribute('aria-haspopup')==='dialog'&&/Language/.test(document.activeElement.textContent));
   // Recurring drafts live in the Automation builder: a draft definition, an edit, then the owner's controls.
   const title='Autumn concert '+width;
   await page.goto(base+'/app/automations');await page.getByRole('heading',{name:'Automations',level:1}).waitFor();
   await hydrated(page,page.getByRole('button',{name:'New automation'}).first());
   await page.getByRole('button',{name:'New automation'}).first().click();
   const builder=page.getByRole('dialog',{name:/automation/i}).first();
   await builder.getByLabel('Name',{exact:true}).fill(title);
   const goal=builder.getByLabel('What should each draft be about?');
   await goal.fill(title);
   await builder.getByLabel('Who is it for?').fill('繁體中文與 English readers');
   await goal.focus();await page.keyboard.press('Tab');
   assert.equal(await builder.getByLabel('Who is it for?').evaluate(el=>el===document.activeElement),true);
   await builder.getByRole('tab',{name:/Where/}).click();
   await builder.getByRole('button',{name:'Choose accounts or folders'}).click();
   const bloom=page.getByRole('dialog').filter({has:page.getByRole('checkbox',{name:/^Festival/})}).last();
   await bloom.getByRole('checkbox',{name:/^Festival/}).click();await bloom.getByRole('button',{name:/^Done/}).click();
   await builder.getByRole('tab',{name:/Review/}).click();
   await builder.getByLabel('Writer').selectOption('deterministic-preview');
   await builder.getByLabel('Cost limit per run (USD)').fill('0');
   await builder.getByRole('button',{name:'Save as draft',exact:true}).click();
   await builder.waitFor({state:'hidden',timeout:30000});
   const card=page.locator('article').filter({has:page.getByRole('heading',{name:title})});
   await card.waitFor();await page.reload();await hydrated(page,card.getByRole('button',{name:'Edit'}));
   // An event brief saves without its date and venue, but cannot be activated until they are added.
   assert.equal(await card.getByRole('button',{name:'Activate'}).isDisabled(),true);
   await card.getByText(/Add the event date and venue to activate\./).waitFor();
   await card.getByRole('button',{name:'Edit'}).click();
   const edit=page.getByRole('dialog',{name:/automation/i}).first();
   assert.equal(await edit.getByLabel('What should each draft be about?').inputValue(),title);
   await edit.getByLabel('What should each draft be about?').fill(title+' reviewed');
   await edit.getByLabel('Event date',{exact:true}).fill('18 October, 7:30 pm');
   await edit.getByLabel('Venue',{exact:true}).fill('City Hall');
   await edit.getByRole('tab',{name:/Review/}).click();
   await edit.getByRole('button',{name:'Save as draft',exact:true}).click();
   await edit.waitFor({state:'hidden',timeout:30000});
   // Links that name an automation (the chat reply card, the planner) open that automation's editor, after a fresh load.
   snap=await api('GET',`/api/workspaces/${wid}`);
   const saved=snap.state.raffi.campaignPlanning.recurringTasks.findLast(t=>t.name===title);
   await page.goto(base+'/app/automations?edit='+encodeURIComponent(saved.id));
   const linked=page.getByRole('dialog',{name:/automation/i}).first();
   await hydrated(page,linked.getByLabel('Name',{exact:true}));
   assert.deepEqual([await linked.getByLabel('Name',{exact:true}).inputValue(),await linked.getByLabel('What should each draft be about?').inputValue(),await linked.getByLabel('Venue',{exact:true}).inputValue()],[title,title+' reviewed','City Hall']);
   await page.keyboard.press('Escape');await linked.waitFor({state:'hidden'});
   await hydrated(page,card.getByRole('button',{name:'Activate'}));
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await card.getByRole('button',{name:'Activate'}).click();await card.getByRole('button',{name:'Pause'}).waitFor();
   await card.getByRole('button',{name:'Pause'}).click();await card.getByRole('button',{name:'Resume'}).waitFor();
   await card.getByRole('button',{name:'Resume'}).click();await card.getByRole('button',{name:'Pause'}).waitFor();
   await card.getByRole('button',{name:'Cancel automation'}).click();
   const confirm=page.getByRole('dialog').filter({hasText:'No more drafts will be prepared'});await confirm.waitFor();
   await confirm.getByRole('button',{name:'Cancel automation'}).click();await confirm.waitFor({state:'hidden'});
   await page.reload();await page.getByRole('heading',{name:'Automations',level:1}).waitFor();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.addScriptTag({path:require.resolve('axe-core/axe.min.js',{paths:[process.env.PLAYWRIGHT_MODULE || resolve(__dirname,'../node_modules')]})});
   const audit=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,help:v.help,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))};});
   audits.push({width,...audit});
   writeFileSync(resolve(out,'browser-accessibility.json'),JSON.stringify({execution:'local Chromium axe-core; reduced motion; keyboard tab; no human conformance claim',audits},null,2));
   await page.screenshot({path:resolve(out,`durable-automation-${width}.png`),fullPage:true});
   await page.goto(base+'/app/workspace/brand');
   const sample='先聽一聽。\nA small musical observation. 🎵';
   const sampleField=page.getByLabel('Writing sample',{exact:true});
   await hydrated(page,sampleField);
   await sampleField.fill(sample);
   await page.getByRole('checkbox',{name:/I wrote or have permission to use this text and consent to private retention/}).check();
   await page.getByRole('button',{name:'Retain samples',exact:true}).click();
   const sampleRow=page.locator('li').filter({has:page.getByText(sample,{exact:true})});await sampleRow.waitFor();
   await sampleRow.getByRole('checkbox').click();
   await sampleRow.getByRole('checkbox',{checked:true}).waitFor();
   await sampleRow.getByRole('button',{name:'Allow local analysis',exact:true}).click();
   await sampleRow.getByText(/Allowed for/).waitFor();
   await sampleRow.getByRole('combobox').selectOption('local-cli');
   await sampleRow.getByRole('button',{name:'Allow this writer to use style'}).click();
   await sampleRow.getByText(/Allowed for.*generation/).waitFor();
   await page.reload();await page.getByText(sample,{exact:true}).waitFor();
   await hydrated(page,page.getByRole('button',{name:'Analyse locally',exact:true}));
   await page.getByRole('button',{name:'Analyse locally',exact:true}).click();
   await page.getByText('Voice proposal ready for review.',{exact:true}).waitFor();
   await sampleRow.getByRole('button',{name:'Revoke & remove text',exact:true}).click();
   await sampleRow.getByRole('button',{name:'Confirm revoke',exact:true}).click();
   await page.waitForFunction(text => ![...document.querySelectorAll('p,blockquote')].some(el => el.textContent === text),sample);
   await page.reload();assert.equal(await page.getByText(sample,{exact:true}).count(),0);
   // Measured right after the reload, while the workspace may still be loading (its skeleton once widened a 320px screen).
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'no horizontal scroll on Brand');
   if(width===1440) {
    const htmlResponse=await context.request.get(base+'/app');const html=await htmlResponse.text();
    assert.match(htmlResponse.headers()['cache-control'],/no-store/);
    // The heading mixes plain and emphasised text, so compare its text with tags and React's text separators removed.
    const heading=(html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)?.[1]??'').replace(/<!--[\s\S]*?-->/g,'').replace(/<[^>]+>/g,'').replace(/&#x27;/g,'\'');
    assert.equal(heading,HOME_TITLE,'server-rendered Home heading');
    assert.ok(html.includes(wid),'authenticated workspace is bootstrapped');
    assert.equal(html.includes('Bearer dev:'),false);assert.equal(html.includes('dev:'+principal),false);
    const stranger=randomUUID(),other=await browser.newContext({javaScriptEnabled:false});
    await other.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:stranger,url:base},{name:'postriff_workspace',value:wid,url:base}]);
    const bootstrap=await other.request.post(base+'/api/auth/verify',{headers:{Authorization:'Bearer dev:'+stranger,Origin:base,'X-PostRiff-Request':'founder-alpha'},data:{plan:'studio'}});assert.ok(bootstrap.ok());
    const own=await (await other.request.get(base+'/api/workspaces',{headers:{Authorization:'Bearer dev:'+stranger}})).json();
    // JavaScript is off so only server HTML is read. Home streams in a Suspense segment that Next.js reveals with an
    // inline script, so without JavaScript the heading is present but hidden: check presence, not visibility.
    const privatePage=await other.newPage();await privatePage.goto(base+'/app');
    const ownHeading=privatePage.locator('h1');await ownHeading.waitFor({state:'attached'});
    assert.equal((await ownHeading.textContent()).trim(),HOME_TITLE);
    const ownHtml=await privatePage.content();assert.ok(ownHtml.includes(own.workspaces[0].workspaceId));assert.equal(ownHtml.includes(wid),false);assert.equal(ownHtml.includes(title),false);
    // A real private page other than Home (/app/account itself is a 404); the proxy overwrites the hint there.
    const forged=await other.request.get(base+'/app/account/profile',{headers:{'x-postriff-home-render':'1'}});assert.equal(forged.status(),200);assert.equal((await forged.text()).includes(own.workspaces[0].workspaceId),false);
    await other.close();
    const anonymous=await browser.newContext();const anon=await anonymous.request.get(base+'/app');assert.equal((await anon.text()).includes(wid),false);await anonymous.close();
    results.push({privateSSR:true,noSharedCache:true,foreignSelectionRejected:true,anonymousPrivateData:false,forgedRouteHintRejected:true,serverHtmlHasOwnHome:true});
   }
   snap=await api('GET','/api/workspaces/'+wid);
   const planning=snap.state.raffi.campaignPlanning;
   const task=planning.recurringTasks.findLast(t=>t.name===title);
   assert.equal(task.status,'cancelled');
   const campaign=planning.campaigns.find(c=>c.id===task.campaignId);
   assert.equal(campaign.goal,title+' reviewed');assert.ok(campaign.version>=2);
   assert.deepEqual([campaign.facts.date,campaign.facts.venue,campaign.missingFacts],['18 October, 7:30 pm','City Hall',[]]);
   assert.equal(snap.state.sources.find(s=>s.kind==='voice_sample').text,'');
   assert.equal(snap.state.phase2.jobs.length,0);
   assert.deepEqual(errors,[]);
   await page.screenshot({path:resolve(out,`durable-voice-${width}.png`),fullPage:true});
   results.push({width,automationControlsPersisted:true,eventFactsRequiredBeforeActivation:true,editLinkOpenedCorrectAutomation:true,languageDialogKeyboard:true,keyboardTab:true,automationEditPersisted:true,voiceGrantPersisted:true,revocationPersisted:true,pageErrors:errors.length});
   await context.close();
  }
  writeFileSync(resolve(out,'durable-browser.json'),JSON.stringify({status:'PASS',execution:'real local frontend/API/PostgreSQL; synthetic identity/provider; no paid calls',results},null,2)+'\n');
  console.log(JSON.stringify(results));
  assert.deepEqual(audits.flatMap(a=>a.violations.filter(v=>['critical','serious'].includes(v.impact))),[], 'Unresolved serious accessibility failures');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
